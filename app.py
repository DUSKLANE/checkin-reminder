from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'

# 初始化扩展
db = SQLAlchemy(app)
CORS(app)

# 初始化调度器
scheduler = BackgroundScheduler()
scheduler.start()

# 数据模型
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    reminder_time = db.Column(db.String(5), nullable=False)  # HH:MM 格式
    email = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'reminder_time': self.reminder_time,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class CheckIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    check_in_time = db.Column(db.DateTime, default=datetime.now)
    task = db.relationship('Task', backref=db.backref('check_ins', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'check_in_time': self.check_in_time.isoformat() if self.check_in_time else None
        }

# 邮件配置
def send_reminder_email(task):
    """发送提醒邮件"""
    try:
        # 邮件配置 - 请根据实际情况修改
        smtp_server = os.getenv('SMTP_SERVER', 'smtpdm.aliyun.com')
        smtp_port = int(os.getenv('SMTP_PORT', '465'))
        sender_email = os.getenv('SENDER_EMAIL', '')
        sender_password = os.getenv('SENDER_PASSWORD', '')

        # 创建邮件
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = task.email
        msg['Subject'] = f'签到提醒 - {task.title}'
        
        # 读取HTML模板
        with open('templates/email_template.html', 'r', encoding='utf-8') as file:
            html_template = file.read()

        # 替换模板中的占位符
        html_body = html_template.replace('{{ task_title }}', task.title)
        html_body = html_body.replace('{{ reminder_time }}', task.reminder_time)
        html_body = html_body.replace('{{ task_description }}', task.description or '无')

        # 添加HTML内容
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        # 发送邮件
        if smtp_port == 465:
            # 使用SSL连接
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
        else:
            # 使用TLS连接
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
            
        print(f"提醒邮件已发送到 {task.email}")
        return True
        
    except Exception as e:
        print(f"发送邮件失败: {e}")
        return False

def check_and_send_reminders():
    """检查并发送提醒邮件"""
    # 在Flask应用上下文中运行
    with app.app_context():
        try:
            current_time = datetime.now()
            current_time_str = current_time.strftime('%H:%M')
            
            # 获取当前时间需要提醒的活跃任务
            active_tasks = Task.query.filter_by(is_active=True).all()
            
            for task in active_tasks:
                if task.reminder_time == current_time_str:
                    # 检查今天是否已经签到
                    today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_end = today_start + timedelta(days=1)
                    
                    today_check_in = CheckIn.query.filter(
                        CheckIn.task_id == task.id,
                        CheckIn.check_in_time >= today_start,
                        CheckIn.check_in_time < today_end
                    ).first()
                    
                    # 如果没有签到，发送提醒邮件
                    if not today_check_in:
                        print(f"发送提醒邮件到 {task.email} - 任务: {task.title}")
                        send_reminder_email(task)
                    else:
                        print(f"任务 {task.title} 今日已签到，跳过提醒")
        except Exception as e:
            print(f"检查提醒时发生错误: {e}")

# 添加定时检查任务到调度器
scheduler.add_job(
    func=check_and_send_reminders,
    trigger=CronTrigger(minute='*'),  # 每分钟检查一次
    id='reminder_checker',
    name='Check and send reminders',
    replace_existing=True
)

# 全局错误处理器
@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': '服务器内部错误'}), 500

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': '资源未找到'}), 404

# 路由
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """获取所有任务"""
    tasks = Task.query.all()
    return jsonify([task.to_dict() for task in tasks])

@app.route('/api/tasks', methods=['POST'])
def create_task():
    """创建新任务"""
    try:
        data = request.json
        
        if not data or not data.get('title') or not data.get('reminder_time') or not data.get('email'):
            return jsonify({'error': '缺少必要字段'}), 400
        
        task = Task(
            title=data['title'],
            description=data.get('description', ''),
            reminder_time=data['reminder_time'],
            email=data['email']
        )
        
        db.session.add(task)
        db.session.commit()
        
        return jsonify(task.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"创建任务失败: {e}")
        return jsonify({'error': '创建任务失败'}), 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """更新任务"""
    try:
        task = Task.query.get_or_404(task_id)
        data = request.json
        
        if 'title' in data:
            task.title = data['title']
        if 'description' in data:
            task.description = data['description']
        if 'reminder_time' in data:
            task.reminder_time = data['reminder_time']
        if 'email' in data:
            task.email = data['email']
        if 'is_active' in data:
            task.is_active = data['is_active']
        
        db.session.commit()
        return jsonify(task.to_dict())
    except Exception as e:
        db.session.rollback()
        print(f"更新任务失败: {e}")
        return jsonify({'error': '更新任务失败'}), 500

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除任务"""
    try:
        task = Task.query.get_or_404(task_id)
        
        # 先删除相关的签到记录
        CheckIn.query.filter_by(task_id=task_id).delete()
        
        # 然后删除任务
        db.session.delete(task)
        db.session.commit()
        
        return jsonify({'message': '任务已删除'})
    except Exception as e:
        db.session.rollback()
        print(f"删除任务失败: {e}")
        return jsonify({'error': '删除任务失败'}), 500

@app.route('/api/tasks/<int:task_id>/checkin', methods=['POST'])
def check_in(task_id):
    """签到"""
    try:
        task = Task.query.get_or_404(task_id)
        
        # 检查今天是否已经签到
        current_time = datetime.now()
        today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        existing_check_in = CheckIn.query.filter(
            CheckIn.task_id == task_id,
            CheckIn.check_in_time >= today_start,
            CheckIn.check_in_time < today_end
        ).first()
        
        if existing_check_in:
            return jsonify({'error': '今天已经签到过了'}), 400
        
        # 创建签到记录
        check_in = CheckIn(task_id=task_id)
        db.session.add(check_in)
        db.session.commit()
        
        return jsonify(check_in.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"签到失败: {e}")
        return jsonify({'error': '签到失败'}), 500

@app.route('/api/tasks/<int:task_id>/checkins', methods=['GET'])
def get_checkins(task_id):
    """获取任务的签到记录"""
    check_ins = CheckIn.query.filter_by(task_id=task_id).order_by(CheckIn.check_in_time.desc()).all()
    return jsonify([check_in.to_dict() for check_in in check_ins])

@app.route('/api/checkins/today', methods=['GET'])
def get_today_checkins():
    """获取今天的签到记录"""
    current_time = datetime.now()
    today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    check_ins = CheckIn.query.filter(
        CheckIn.check_in_time >= today_start,
        CheckIn.check_in_time < today_end
    ).all()
    
    return jsonify([check_in.to_dict() for check_in in check_ins])

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    print("定时任务签到提醒系统已启动！")
    print("请确保配置了正确的邮件设置")
    app.run(debug=True, host='0.0.0.0', port=5000)
