import logging
import os
import re
import random
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document, PhotoSize
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    JobQueue
)
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

Base = declarative_base()
engine = create_engine('sqlite:///exam_prep.db', echo=False)
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String)
    reminder_time = Column(String, default='09:00')
    reminder_enabled = Column(Boolean, default=False)
    disciplines = relationship("Discipline", back_populates="user", cascade="all, delete-orphan")

class Discipline(Base):
    __tablename__ = 'disciplines'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String, nullable=False)
    total_questions = Column(Integer, default=0)
    studied_questions = Column(Integer, default=0)
    exam_date = Column(DateTime, nullable=True)
    is_shared = Column(Boolean, default=False)
    share_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User", back_populates="disciplines")
    questions = relationship("Question", back_populates="discipline", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = 'questions'
    id = Column(Integer, primary_key=True)
    discipline_id = Column(Integer, ForeignKey('disciplines.id'))
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    cheat_sheet = Column(Text, nullable=True)
    is_studied = Column(Boolean, default=False)
    difficulty = Column(String, default='medium')
    last_reviewed = Column(DateTime, nullable=True)
    review_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    discipline = relationship("Discipline", back_populates="questions")
    files = relationship("QuestionFile", back_populates="question", cascade="all, delete-orphan")

class QuestionFile(Base):
    __tablename__ = 'question_files'
    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey('questions.id'))
    file_id = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    caption = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.now)
    question = relationship("Question", back_populates="files")

class SharedAccess(Base):
    __tablename__ = 'shared_access'
    id = Column(Integer, primary_key=True)
    discipline_id = Column(Integer, ForeignKey('disciplines.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    can_edit = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.now)

Base.metadata.create_all(engine)

# Состояния
(
    DISCIPLINE_NAME, DISCIPLINE_QUESTIONS, DISCIPLINE_DATE,
    QUESTION_TITLE, QUESTION_CHEATSHEET, QUESTION_DIFFICULTY,
    EDIT_CHEATSHEET, SEARCH_QUERY,
    REMINDER_TIME, SHARE_CODE, JOIN_CODE,
    FILE_CAPTION, FILE_UPLOAD
) = range(13)

def back_button(data='main_menu'):
    return [InlineKeyboardButton("◀️ Назад", callback_data=data)]

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📚 Мои дисциплины", callback_data='my_disciplines')],
        [InlineKeyboardButton("➕ Добавить дисциплину", callback_data='add_discipline')],
        [InlineKeyboardButton("📊 Прогресс подготовки", callback_data='progress')],
        [InlineKeyboardButton("🔍 Поиск по шпаргалкам", callback_data='search_cheatsheets')],
        [InlineKeyboardButton("📅 До сессии", callback_data='countdown')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='settings')]
    ]
    return InlineKeyboardMarkup(keyboard)

def settings_menu():
    keyboard = [
        [InlineKeyboardButton("🔔 Напоминания", callback_data='reminder_settings')],
        [InlineKeyboardButton("👥 Совместный доступ", callback_data='sharing_menu')],
        [InlineKeyboardButton("📤 Экспорт данных", callback_data='export_menu')],
        back_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def discipline_menu(disc_id):
    keyboard = [
        [InlineKeyboardButton("📝 Список вопросов", callback_data=f'questions_list_{disc_id}')],
        [InlineKeyboardButton("➕ Добавить вопрос", callback_data=f'add_question_{disc_id}')],
        [InlineKeyboardButton("📖 Режим заучивания", callback_data=f'study_mode_{disc_id}')],
        [InlineKeyboardButton("🎯 Самопроверка", callback_data=f'self_check_{disc_id}')],
        [InlineKeyboardButton("📊 Прогресс по дисциплине", callback_data=f'disc_progress_{disc_id}')],
        [InlineKeyboardButton("✏️ Изменить экзамен", callback_data=f'edit_discipline_{disc_id}')],
        [InlineKeyboardButton("🔗 Поделиться", callback_data=f'share_discipline_{disc_id}')],
        [InlineKeyboardButton("📤 Экспорт", callback_data=f'export_discipline_{disc_id}')],
        [InlineKeyboardButton("🗑 Удалить дисциплину", callback_data=f'delete_discipline_{disc_id}')],
        back_button('my_disciplines')
    ]
    return InlineKeyboardMarkup(keyboard)

def question_menu(q_id, disc_id):
    keyboard = [
        [InlineKeyboardButton("✅ Отметить изученным", callback_data=f'mark_studied_{q_id}')],
        [InlineKeyboardButton("✏️ Редактировать шпаргалку", callback_data=f'edit_cheatsheet_{q_id}')],
        [InlineKeyboardButton("📎 Добавить файл", callback_data=f'add_file_{q_id}')],
        [InlineKeyboardButton("📁 Файлы вопроса", callback_data=f'view_files_{q_id}')],
        [InlineKeyboardButton("📝 Изменить вопрос", callback_data=f'edit_question_{q_id}')],
        [InlineKeyboardButton("🗑 Удалить вопрос", callback_data=f'delete_question_{q_id}')],
        back_button(f'questions_list_{disc_id}')
    ]
    return InlineKeyboardMarkup(keyboard)

def difficulty_keyboard(disc_id):
    keyboard = [
        [InlineKeyboardButton("🟢 Лёгкий", callback_data='diff_easy')],
        [InlineKeyboardButton("🟡 Средний", callback_data='diff_medium')],
        [InlineKeyboardButton("🔴 Сложный", callback_data='diff_hard')],
        back_button(f'add_question_{disc_id}')
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    if not user:
        user = User(
            telegram_id=update.effective_user.id,
            username=update.effective_user.username
        )
        session.add(user)
        session.commit()
    
    session.close()
    
    text = (
        f"🎓 Привет, {update.effective_user.first_name}!\n\n"
        "Я твой помощник в подготовке к сессии. Здесь ты можешь:\n"
        "• 📚 Хранить все дисциплины и билеты\n"
        "• 📝 Создавать сжатые шпаргалки\n"
        "• 📎 Прикреплять файлы (PDF, фото, аудио)\n"
        "• 🎯 Проверять себя без подсказок\n"
        "• 📊 Отслеживать прогресс\n"
        "• 🔍 Искать по шпаргалкам\n"
        "• 👥 Учиться вместе с друзьями\n\n"
        "Всё хранится в одном месте — твоя личная база знаний!"
    )
    
    await update.message.reply_text(text, reply_markup=main_menu())

async def my_disciplines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    disciplines = session.query(Discipline).filter_by(user_id=user.id).all()
    
    shared = session.query(SharedAccess).filter_by(user_id=user.id).all()
    shared_disciplines = []
    for access in shared:
        disc = session.query(Discipline).get(access.discipline_id)
        if disc:
            shared_disciplines.append(disc)
    
    session.close()
    
    all_disciplines = disciplines + shared_disciplines
    
    if not all_disciplines:
        keyboard = [
            [InlineKeyboardButton("➕ Добавить дисциплину", callback_data='add_discipline')],
            [InlineKeyboardButton("🔗 Присоединиться", callback_data='join_discipline')],
            back_button()
        ]
        await query.edit_message_text(
            "📭 У тебя пока нет дисциплин.\n\nДобавь первую или присоединись к друзьям:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "📚 *Твои дисциплины:*\n\n"
    keyboard = []
    
    for disc in all_disciplines:
        is_shared = "👥 " if disc.user_id != user.id else ""
        progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
        exam_text = f" (экзамен: {disc.exam_date.strftime('%d.%m')})" if disc.exam_date else ""
        text += f"• {is_shared}*{disc.name}*{exam_text}\n"
        text += f"  Прогресс: {disc.studied_questions}/{disc.total_questions} ({progress:.0f}%)\n\n"
        keyboard.append([InlineKeyboardButton(
            f"{is_shared}{disc.name} ({disc.studied_questions}/{disc.total_questions})", 
            callback_data=f'discipline_{disc.id}'
        )])
    
    keyboard.append([InlineKeyboardButton("🔗 Присоединиться к дисциплине", callback_data='join_discipline')])
    keyboard.append(back_button())
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def discipline_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[1])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    has_access = disc.user_id == user.id or session.query(SharedAccess).filter_by(
        discipline_id=disc_id, user_id=user.id
    ).first()
    
    session.close()
    
    if not disc or not has_access:
        await query.edit_message_text("❌ Дисциплина не найдена или нет доступа", reply_markup=main_menu())
        return
    
    progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
    exam_text = f"\n📅 Экзамен: *{disc.exam_date.strftime('%d.%m.%Y')}*" if disc.exam_date else ""
    shared_text = "\n👥 *Совместный доступ*" if disc.is_shared else ""
    
    text = (
        f"📖 *{disc.name}*{shared_text}\n"
        f"📝 Всего вопросов: {disc.total_questions}\n"
        f"✅ Изучено: {disc.studied_questions}\n"
        f"📊 Прогресс: {progress:.1f}%{exam_text}"
    )
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=discipline_menu(disc_id))

async def add_discipline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📚 Введите название дисциплины:\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button('my_disciplines')])
    )
    return DISCIPLINE_NAME

async def get_discipline_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['disc_name'] = update.message.text
    await update.message.reply_text(
        "🔢 Сколько вопросов (билетов) в этой дисциплине?\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button('my_disciplines')])
    )
    return DISCIPLINE_QUESTIONS

async def get_discipline_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if count <= 0:
            raise ValueError
        context.user_data['disc_questions'] = count
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число:\n\n(или /cancel для отмены)",
            reply_markup=InlineKeyboardMarkup([back_button('my_disciplines')])
        )
        return DISCIPLINE_QUESTIONS
    
    await update.message.reply_text(
        "📅 Введите дату экзамена в формате ДД.ММ.ГГГГ\n"
        "(или отправьте '-' если дата неизвестна)\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button('my_disciplines')])
    )
    return DISCIPLINE_DATE

async def get_discipline_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    exam_date = None
    
    if text != '-':
        try:
            exam_date = datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат! Попробуйте снова (ДД.ММ.ГГГГ):\n\n(или /cancel для отмены)",
                reply_markup=InlineKeyboardMarkup([back_button('my_disciplines')])
            )
            return DISCIPLINE_DATE
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    disc = Discipline(
        user_id=user.id,
        name=context.user_data['disc_name'],
        total_questions=context.user_data['disc_questions'],
        exam_date=exam_date
    )
    
    session.add(disc)
    session.commit()
    disc_id = disc.id
    session.close()
    
    date_text = f" ({exam_date.strftime('%d.%m.%Y')})" if exam_date else ""
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить вопросы", callback_data=f'add_question_{disc_id}')],
        [InlineKeyboardButton("📚 К дисциплинам", callback_data='my_disciplines')],
        back_button()
    ]
    
    await update.message.reply_text(
        f"✅ Дисциплина добавлена!\n\n"
        f"📖 *{context.user_data['disc_name']}*{date_text}\n"
        f"📝 Вопросов: {context.user_data['disc_questions']}\n\n"
        f"Теперь добавь вопросы и шпаргалки:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return ConversationHandler.END

async def questions_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    questions = session.query(Question).filter_by(discipline_id=disc_id).order_by(Question.number).all()
    session.close()
    
    text = f"📝 *{disc.name}* — Вопросы:\n\n"
    keyboard = []
    
    if not questions:
        text += "Пока нет добавленных вопросов.\n"
    else:
        for q in questions:
            status = "✅" if q.is_studied else "⬜"
            diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
            has_cheat = "📎" if q.cheat_sheet else ""
            has_files = "📁" if q.files else ""
            text += f"{status} *Вопрос {q.number}*: {q.title} {has_cheat}{has_files} {diff_emoji[q.difficulty]}\n"
            keyboard.append([InlineKeyboardButton(
                f"{status} Вопрос {q.number}: {q.title[:30]}{'...' if len(q.title) > 30 else ''}",
                callback_data=f'question_{q.id}'
            )])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить вопрос", callback_data=f'add_question_{disc_id}')])
    keyboard.append(back_button(f'discipline_{disc_id}'))
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def question_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[1])
    
    session = Session()
    q = session.query(Question).get(q_id)
    session.close()
    
    if not q:
        await query.edit_message_text("❌ Вопрос не найден")
        return
    
    diff_emoji = {"easy": "🟢 Лёгкий", "medium": "🟡 Средний", "hard": "🔴 Сложный"}
    status = "✅ Изучено" if q.is_studied else "⬜ Не изучено"
    last_review = f"\n🔄 Последняя проверка: {q.last_reviewed.strftime('%d.%m')}" if q.last_reviewed else ""
    files_count = f"\n📁 Файлов: {len(q.files)}" if q.files else ""
    
    text = (
        f"📝 *Вопрос {q.number}*\n"
        f"*{q.title}*\n\n"
        f"📊 Сложность: {diff_emoji[q.difficulty]}\n"
        f"📋 Статус: {status}{last_review}{files_count}\n\n"
    )
    
    if q.cheat_sheet:
        text += f"📎 *Шпаргалка:*\n```{q.cheat_sheet}```"
    else:
        text += "📎 *Шпаргалка:* не добавлена"
    
    await query.edit_message_text(
        text, 
        parse_mode='MarkdownV2',
        reply_markup=question_menu(q_id, q.discipline_id)
    )

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    context.user_data['current_discipline'] = disc_id
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    existing = session.query(Question).filter_by(discipline_id=disc_id).count()
    session.close()
    
    context.user_data['next_number'] = existing + 1
    
    await query.edit_message_text(
        f"📝 Добавление вопроса к *{disc.name}*\n"
        f"Номер вопроса: {existing + 1}\n\n"
        f"Введите название/формулировку вопроса:\n\n(или /cancel для отмены)",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([back_button(f'questions_list_{disc_id}')])
    )
    return QUESTION_TITLE

async def get_question_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['q_title'] = update.message.text
    disc_id = context.user_data['current_discipline']
    
    await update.message.reply_text(
        "📝 Введите сжатую шпаргалку по этому вопросу.\n"
        "Советы для хорошей шпаргалки:\n"
        "• Используй ключевые слова и формулы\n"
        "• Структурируй пунктами\n"
        "• Выдели главное, убери воду\n\n"
        "Отправь текст шпаргалки (или '-' чтобы пропустить):\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button(f'questions_list_{disc_id}')])
    )
    return QUESTION_CHEATSHEET

async def get_cheatsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    disc_id = context.user_data['current_discipline']
    
    context.user_data['q_cheatsheet'] = None if text == '-' else text
    
    await update.message.reply_text(
        "Выберите сложность вопроса:",
        reply_markup=difficulty_keyboard(disc_id)
    )
    return QUESTION_DIFFICULTY

async def get_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    difficulty = query.data.split('_')[1]
    disc_id = context.user_data['current_discipline']
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    
    q = Question(
        discipline_id=disc_id,
        number=context.user_data['next_number'],
        title=context.user_data['q_title'],
        cheat_sheet=context.user_data['q_cheatsheet'],
        difficulty=difficulty
    )
    
    session.add(q)
    disc.total_questions = session.query(Question).filter_by(discipline_id=disc_id).count()
    session.commit()
    session.close()
    
    diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
    
    keyboard = [
        [InlineKeyboardButton("➕ Ещё вопрос", callback_data=f'add_question_{disc_id}')],
        [InlineKeyboardButton("📋 Список вопросов", callback_data=f'questions_list_{disc_id}')],
        [InlineKeyboardButton("📚 К дисциплинам", callback_data='my_disciplines')],
        back_button()
    ]
    
    await query.edit_message_text(
        f"✅ Вопрос добавлен!\n\n"
        f"📝 *Вопрос {context.user_data['next_number']}*\n"
        f"{context.user_data['q_title']}\n\n"
        f"📎 Шпаргалка: {'добавлена' if context.user_data['q_cheatsheet'] else 'не добавлена'}\n"
        f"Сложность: {diff_emoji[difficulty]}\n\n"
        f"Что дальше?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return ConversationHandler.END

# ========== ФАЙЛЫ ==========

async def add_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[2])
    context.user_data['file_question_id'] = q_id
    
    await query.edit_message_text(
        "📎 *Добавление файла*\n\n"
        "Отправь мне файл, фото, аудио или видео.\n"
        "Поддерживаются:\n"
        "• 📄 Документы (PDF, DOC, TXT)\n"
        "• 🖼 Фото\n"
        "• 🎵 Аудио/голосовые\n"
        "• 🎥 Видео\n\n"
        "Отправь файл сейчас (или /cancel для отмены):",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([back_button(f'question_{q_id}')])
    )
    return FILE_UPLOAD

async def process_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q_id = context.user_data['file_question_id']
    
    file_id = None
    file_type = None
    file_name = None
    
    if update.message.document:
        file_id = update.message.document.file_id
        file_type = 'document'
        file_name = update.message.document.file_name or "Документ"
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = 'photo'
        file_name = "Фото"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = 'audio'
        file_name = update.message.audio.file_name or "Аудио"
    elif update.message.voice:
        file_id = update.message.voice.file_id
        file_type = 'audio'
        file_name = "Голосовое сообщение"
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = 'video'
        file_name = update.message.video.file_name or "Видео"
    else:
        await update.message.reply_text(
            "❌ Неподдерживаемый тип файла.\n\nПопробуйте снова (или /cancel):",
            reply_markup=InlineKeyboardMarkup([back_button(f'question_{q_id}')])
        )
        return FILE_UPLOAD
    
    context.user_data['pending_file'] = {
        'file_id': file_id,
        'file_type': file_type,
        'file_name': file_name
    }
    
    await update.message.reply_text(
        f"✅ Получил: {file_name}\n\n"
        f"Введите подпись к файлу (или отправьте '-' без подписи):\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button(f'question_{q_id}')])
    )
    return FILE_CAPTION

async def save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.text
    q_id = context.user_data['file_question_id']
    
    if caption == '-':
        caption = None
    
    pending = context.user_data['pending_file']
    
    session = Session()
    q = session.query(Question).get(q_id)
    disc_id = q.discipline_id
    
    file_record = QuestionFile(
        question_id=q_id,
        file_id=pending['file_id'],
        file_type=pending['file_type'],
        file_name=pending['file_name'],
        caption=caption
    )
    
    session.add(file_record)
    session.commit()
    session.close()
    
    type_emoji = {'document': '📄', 'photo': '🖼', 'audio': '🎵', 'video': '🎥'}
    
    await update.message.reply_text(
        f"{type_emoji[pending['file_type']]} Файл добавлен!\n\n"
        f"*{pending['file_name']}*\n"
        f"{caption if caption else ''}\n\n"
        f"К вопросу можно прикрепить несколько файлов.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📎 Добавить ещё файл", callback_data=f'add_file_{q_id}')],
            [InlineKeyboardButton("📁 Посмотреть все файлы", callback_data=f'view_files_{q_id}')],
            [InlineKeyboardButton("📋 К списку вопросов", callback_data=f'questions_list_{disc_id}')],
            back_button(f'question_{q_id}')
        ])
    )
    
    return ConversationHandler.END

async def view_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[2])
    
    session = Session()
    q = session.query(Question).get(q_id)
    files = session.query(QuestionFile).filter_by(question_id=q_id).all()
    session.close()
    
    if not files:
        await query.edit_message_text(
            "📭 К этому вопросу пока не прикреплены файлы.\n\n"
            "Добавь первый:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📎 Добавить файл", callback_data=f'add_file_{q_id}')],
                back_button(f'question_{q_id}')
            ])
        )
        return
    
    type_emoji = {'document': '📄', 'photo': '🖼', 'audio': '🎵', 'video': '🎥'}
    
    await query.edit_message_text(
        f"📁 *Файлы вопроса {q.number}:* {q.title}\n\n"
        f"Всего файлов: {len(files)}",
        parse_mode='Markdown'
    )
    
    for f in files:
        caption = f"{type_emoji[f.file_type]} *{f.file_name}*\n{f.caption if f.caption else ''}"
        
        if f.file_type == 'document':
            await query.message.reply_document(document=f.file_id, caption=caption, parse_mode='Markdown')
        elif f.file_type == 'photo':
            await query.message.reply_photo(photo=f.file_id, caption=caption, parse_mode='Markdown')
        elif f.file_type == 'audio':
            await query.message.reply_audio(audio=f.file_id, caption=caption, parse_mode='Markdown')
        elif f.file_type == 'video':
            await query.message.reply_video(video=f.file_id, caption=caption, parse_mode='Markdown')
    
    keyboard = [
        [InlineKeyboardButton("📎 Добавить файл", callback_data=f'add_file_{q_id}')],
        [InlineKeyboardButton("🗑 Управление файлами", callback_data=f'manage_files_{q_id}')],
        back_button(f'question_{q_id}')
    ]
    
    await query.message.reply_text(
        "Все файлы отправлены 👆",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def manage_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[2])
    
    session = Session()
    files = session.query(QuestionFile).filter_by(question_id=q_id).all()
    session.close()
    
    keyboard = []
    for f in files:
        keyboard.append([InlineKeyboardButton(
            f"🗑 {f.file_name[:40]}{'...' if len(f.file_name) > 40 else ''}",
            callback_data=f'delete_file_{f.id}'
        )])
    
    keyboard.append(back_button(f'question_{q_id}'))
    
    await query.edit_message_text(
        "🗑 Выбери файл для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split('_')[2])
    
    session = Session()
    f = session.query(QuestionFile).get(file_id)
    q_id = f.question_id
    session.delete(f)
    session.commit()
    session.close()
    
    await query.edit_message_text(
        "✅ Файл удалён.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 К файлам вопроса", callback_data=f'view_files_{q_id}')],
            back_button(f'question_{q_id}')
        ])
    )

# ========== САМОПРОВЕРКА ==========

async def self_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    questions = session.query(Question).filter_by(discipline_id=disc_id).all()
    session.close()
    
    if not questions:
        keyboard = [
            [InlineKeyboardButton("➕ Добавить вопрос", callback_data=f'add_question_{disc_id}')],
            back_button(f'discipline_{disc_id}')
        ]
        await query.edit_message_text(
            "📭 В этой дисциплине пока нет вопросов.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    context.user_data['check_questions'] = [q.id for q in questions]
    context.user_data['check_index'] = 0
    context.user_data['check_correct'] = 0
    
    await show_check_question(update, context)

async def show_check_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q_ids = context.user_data['check_questions']
    idx = context.user_data['check_index']
    
    if idx >= len(q_ids):
        correct = context.user_data['check_correct']
        total = len(q_ids)
        percent = (correct / total * 100) if total > 0 else 0
        
        keyboard = [
            [InlineKeyboardButton("🔄 Ещё раз", callback_data=f"self_check_{context.user_data.get('check_disc_id', 0)}")],
            back_button('main_menu')
        ]
        
        await update.callback_query.edit_message_text(
            f"🎯 *Самопроверка завершена!*\n\n"
            f"✅ Правильно: {correct} из {total} ({percent:.0f}%)\n\n"
            f"{'🔥 Отличный результат!' if percent >= 80 else '💪 Хорошо, но есть куда стремиться!' if percent >= 50 else '📚 Стоит повторить материал'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    session = Session()
    q = session.query(Question).get(q_ids[idx])
    session.close()
    
    context.user_data['check_disc_id'] = q.discipline_id
    
    has_files = "\n\n📁 *К вопросу прикреплены файлы*" if q.files else ""
    
    text = (
        f"🎯 *Самопроверка* ({idx + 1}/{len(q_ids)})\n\n"
        f"📝 *Вопрос {q.number}:*\n"
        f"{q.title}{has_files}\n\n"
        f"💭 *Вспомни ответ...*\n"
        f"Когда будешь готов, нажми кнопку ниже 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Я знаю ответ!", callback_data='check_know')],
        [InlineKeyboardButton("❌ Не помню", callback_data='check_dont_know')],
        [InlineKeyboardButton("🛑 Завершить", callback_data='check_finish')]
    ]
    
    await update.callback_query.edit_message_text(
        text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_know(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['check_correct'] += 1
    await show_answer(update, context, True)

async def check_dont_know(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_answer(update, context, False)

async def show_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, knew_it):
    q_ids = context.user_data['check_questions']
    idx = context.user_data['check_index']
    
    session = Session()
    q = session.query(Question).get(q_ids[idx])
    q.last_reviewed = datetime.now()
    q.review_count += 1
    session.commit()
    session.close()
    
    status = "✅ Правильно!" if knew_it else "❌ Нужно повторить"
    
    text = (
        f"{status}\n\n"
        f"📝 *Вопрос {q.number}:* {q.title}\n\n"
        f"📎 *Ответ (шпаргалка):*\n```{q.cheat_sheet or 'Нет шпаргалки'}```"
    )
    
    keyboard = [
        [InlineKeyboardButton("▶️ Следующий вопрос", callback_data='check_next')],
        [InlineKeyboardButton("🛑 Завершить", callback_data='check_finish')]
    ]
    
    await update.callback_query.edit_message_text(
        text, parse_mode='MarkdownV2', reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    if q.files:
        type_emoji = {'document': '📄', 'photo': '🖼', 'audio': '🎵', 'video': '🎥'}
        for f in q.files:
            caption = f"{type_emoji[f.file_type]} *{f.file_name}*\n{f.caption if f.caption else ''}"
            if f.file_type == 'document':
                await update.callback_query.message.reply_document(document=f.file_id, caption=caption, parse_mode='Markdown')
            elif f.file_type == 'photo':
                await update.callback_query.message.reply_photo(photo=f.file_id, caption=caption, parse_mode='Markdown')
            elif f.file_type == 'audio':
                await update.callback_query.message.reply_audio(audio=f.file_id, caption=caption, parse_mode='Markdown')
            elif f.file_type == 'video':
                await update.callback_query.message.reply_video(video=f.file_id, caption=caption, parse_mode='Markdown')

async def check_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['check_index'] += 1
    await show_check_question(update, context)

async def check_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    correct = context.user_data['check_correct']
    idx = context.user_data['check_index']
    total = len(context.user_data['check_questions'])
    
    keyboard = [
        [InlineKeyboardButton("🔄 Продолжить позже", callback_data=f"self_check_{context.user_data.get('check_disc_id', 0)}")],
        back_button('main_menu')
    ]
    
    await update.callback_query.edit_message_text(
        f"🛑 *Проверка прервана*\n\n"
        f"Пройдено: {idx + 1} из {total}\n"
        f"Правильно: {correct}\n\n"
        f"Возвращайся, когда будешь готов!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ========== НАПОМИНАНИЯ ==========

async def reminder_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    session.close()
    
    status = "✅ Включены" if user.reminder_enabled else "❌ Выключены"
    time_text = f"⏰ Время: {user.reminder_time}" if user.reminder_enabled else ""
    
    keyboard = [
        [InlineKeyboardButton("✅ Включить" if not user.reminder_enabled else "❌ Выключить", 
                              callback_data='toggle_reminder')],
        [InlineKeyboardButton("⏰ Изменить время", callback_data='change_reminder_time')],
        back_button('settings')
    ]
    
    await query.edit_message_text(
        f"🔔 *Напоминания*\n\n"
        f"Статус: {status}\n"
        f"{time_text}\n\n"
        f"Каждый день бот будет присылать план на день и напоминать о предстоящих экзаменах.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def toggle_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    user.reminder_enabled = not user.reminder_enabled
    session.commit()
    session.close()
    
    if user.reminder_enabled:
        hour, minute = map(int, user.reminder_time.split(':'))
        context.job_queue.run_daily(
            send_reminder,
            time=datetime.time(hour=hour, minute=minute),
            chat_id=update.effective_chat.id,
            name=str(update.effective_user.id)
        )
    
    await reminder_settings(update, context)

async def change_reminder_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏰ Введите время напоминаний в формате ЧЧ:ММ\n"
        "Например: 09:00 или 18:30\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button('reminder_settings')])
    )
    return REMINDER_TIME

async def save_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    try:
        hour, minute = map(int, text.split(':'))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат! Введите время как ЧЧ:ММ (например, 09:00):\n\n(или /cancel для отмены)",
            reply_markup=InlineKeyboardMarkup([back_button('reminder_settings')])
        )
        return REMINDER_TIME
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    user.reminder_time = text
    if user.reminder_enabled:
        user.reminder_enabled = False
    session.commit()
    session.close()
    
    await update.message.reply_text(
        f"✅ Время напоминаний установлено: {text}\n\n"
        f"Теперь включи напоминания в настройках:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 К настройкам напоминаний", callback_data='reminder_settings')],
            back_button('settings')
        ])
    )
    
    return ConversationHandler.END

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=chat_id).first()
    disciplines = session.query(Discipline).filter_by(user_id=user.id).all()
    session.close()
    
    if not disciplines:
        return
    
    total_q = sum(d.total_questions for d in disciplines)
    studied_q = sum(d.studied_questions for d in disciplines)
    remaining = total_q - studied_q
    
    text = "🌅 *Доброе утро! План на сегодня:*\n\n"
    
    for disc in disciplines:
        if disc.exam_date:
            days_left = (disc.exam_date - datetime.now()).days
            if 0 < days_left <= 7:
                per_day = (disc.total_questions - disc.studied_questions) / days_left
                text += f"📚 *{disc.name}* (экзамен через {days_left} дн.)\n"
                text += f"   Цель на сегодня: ~{per_day:.0f} вопросов\n\n"
    
    text += f"📊 Всего осталось выучить: {remaining} вопросов\n"
    text += "Удачи в подготовке! 💪"
    
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')

# ========== ЭКСПОРТ ==========

async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📤 *Экспорт данных*\n\n"
        "Выбери формат:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Текстовый файл", callback_data='export_txt')],
            [InlineKeyboardButton("📋 Скопировать в буфер", callback_data='export_copy')],
            back_button('settings')
        ])
    )

async def export_discipline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    questions = session.query(Question).filter_by(discipline_id=disc_id).order_by(Question.number).all()
    session.close()
    
    text = f"📖 {disc.name}\n"
    if disc.exam_date:
        text += f"📅 Экзамен: {disc.exam_date.strftime('%d.%m.%Y')}\n"
    text += f"📊 Прогресс: {disc.studied_questions}/{disc.total_questions}\n"
    text += "=" * 40 + "\n\n"
    
    for q in questions:
        status = "✅" if q.is_studied else "⬜"
        diff = {"easy": "Лёгкий", "medium": "Средний", "hard": "Сложный"}[q.difficulty]
        text += f"{status} Вопрос {q.number}: {q.title}\n"
        text += f"   Сложность: {diff}\n"
        if q.cheat_sheet:
            text += f"   Шпаргалка:\n   {q.cheat_sheet}\n"
        if q.files:
            text += f"   📁 Файлов: {len(q.files)}\n"
        text += "\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await query.message.reply_text(f"```{part}```", parse_mode='MarkdownV2')
    else:
        await query.message.reply_text(f"```{text}```", parse_mode='MarkdownV2')
    
    keyboard = [
        [InlineKeyboardButton("📤 Экспортировать ещё", callback_data='export_menu')],
        back_button(f'discipline_{disc_id}')
    ]
    
    await query.edit_message_text(
        "✅ Данные экспортированы!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def export_all_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    disciplines = session.query(Discipline).filter_by(user_id=user.id).all()
    session.close()
    
    filename = f"exam_prep_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    filepath = f"/tmp/{filename}"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("🎓 МОЯ ПОДГОТОВКА К СЕССИИ\n")
        f.write("=" * 50 + "\n\n")
        
        for disc in disciplines:
            f.write(f"\n📖 {disc.name}\n")
            if disc.exam_date:
                f.write(f"📅 Экзамен: {disc.exam_date.strftime('%d.%m.%Y')}\n")
            f.write(f"📊 Прогресс: {disc.studied_questions}/{disc.total_questions}\n")
            f.write("-" * 40 + "\n")
            
            questions = session.query(Question).filter_by(discipline_id=disc.id).order_by(Question.number).all()
            for q in questions:
                status = "✅" if q.is_studied else "⬜"
                f.write(f"\n{status} Вопрос {q.number}: {q.title}\n")
                if q.cheat_sheet:
                    f.write(f"Шпаргалка: {q.cheat_sheet}\n")
                if q.files:
                    f.write(f"Файлов: {len(q.files)}\n")
    
    with open(filepath, 'rb') as f:
        await query.message.reply_document(document=f, filename=filename)
    
    os.remove(filepath)
    
    keyboard = [
        [InlineKeyboardButton("📤 Экспортировать ещё", callback_data='export_menu')],
        back_button('settings')
    ]
    
    await query.edit_message_text(
        "✅ Файл готов!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ========== СОВМЕСТНЫЙ ДОСТУП ==========

async def sharing_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👥 *Совместный доступ*\n\n"
        "• Поделись дисциплиной — друзья смогут добавлять вопросы и файлы\n"
        "• Присоединись к чужой дисциплине по коду\n\n"
        "Выбери действие:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Поделиться дисциплиной", callback_data='share_menu')],
            [InlineKeyboardButton("📥 Присоединиться", callback_data='join_discipline')],
            back_button('settings')
        ])
    )

async def share_discipline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    if disc.user_id != user.id:
        await query.edit_message_text(
            "❌ Только владелец может поделиться дисциплиной.",
            reply_markup=discipline_menu(disc_id)
        )
        session.close()
        return
    
    if not disc.is_shared:
        import secrets
        disc.is_shared = True
        disc.share_code = secrets.token_urlsafe(8)[:8].upper()
        session.commit()
    
    code = disc.share_code
    session.close()
    
    text = (
        f"🔗 *Дисциплина открыта для совместного доступа*\n\n"
        f"📖 {disc.name}\n\n"
        f"🔑 *Код доступа:* `{code}`\n\n"
        f"Отправь этот код друзьям. Они смогут:\n"
        f"• Добавлять вопросы и шпаргалки\n"
        f"• Прикреплять файлы\n"
        f"• Отмечать изученное\n\n"
        f"Твой прогресс сохраняется индивидуально."
    )
    
    keyboard = [
        [InlineKeyboardButton("❌ Закрыть доступ", callback_data=f'unshare_{disc_id}')],
        back_button(f'discipline_{disc_id}')
    ]
    
    await query.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=InlineKeyboardMarkup(keyboard))

async def unshare_discipline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[1])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    disc.is_shared = False
    disc.share_code = None
    session.query(SharedAccess).filter_by(discipline_id=disc_id).delete()
    session.commit()
    session.close()
    
    await query.edit_message_text(
        "✅ Совместный доступ закрыт.",
        reply_markup=discipline_menu(disc_id)
    )

async def join_discipline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📥 Введите код доступа к дисциплине:\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button('sharing_menu')])
    )
    return JOIN_CODE

async def join_discipline_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.upper().strip()
    
    session = Session()
    disc = session.query(Discipline).filter_by(share_code=code, is_shared=True).first()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    if not disc:
        await update.message.reply_text(
            "❌ Неверный код или дисциплина закрыта.\n\nПопробуйте снова (или /cancel):",
            reply_markup=InlineKeyboardMarkup([back_button('sharing_menu')])
        )
        session.close()
        return JOIN_CODE
    
    existing = session.query(SharedAccess).filter_by(discipline_id=disc.id, user_id=user.id).first()
    if existing or disc.user_id == user.id:
        await update.message.reply_text(
            "ℹ️ Вы уже имеете доступ к этой дисциплине.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 Открыть дисциплину", callback_data=f'discipline_{disc.id}')],
                back_button('sharing_menu')
            ])
        )
        session.close()
        return ConversationHandler.END
    
    access = SharedAccess(discipline_id=disc.id, user_id=user.id, can_edit=True)
    session.add(access)
    session.commit()
    session.close()
    
    await update.message.reply_text(
        f"✅ Вы присоединились к дисциплине!\n\n"
        f"📖 *{disc.name}*\n\n"
        f"Теперь вы можете добавлять вопросы, шпаргалки и файлы.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Открыть дисциплину", callback_data=f'discipline_{disc.id}')],
            [InlineKeyboardButton("📚 К моим дисциплинам", callback_data='my_disciplines')]
        ])
    )
    
    return ConversationHandler.END

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========

async def study_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    questions = session.query(Question).filter_by(
        discipline_id=disc_id, 
        is_studied=False
    ).order_by(Question.difficulty.desc(), Question.number).all()
    session.close()
    
    if not questions:
        keyboard = [
            [InlineKeyboardButton("📋 К списку вопросов", callback_data=f'questions_list_{disc_id}')],
            back_button(f'discipline_{disc_id}')
        ]
        await query.edit_message_text(
            "🎉 Все вопросы изучены! Отличная работа!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    q = questions[0]
    diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
    
    text = (
        f"🎓 *Режим заучивания*\n\n"
        f"📖 Вопрос {q.number} из {len(questions)} неизученных\n"
        f"Сложность: {diff_emoji[q.difficulty]}\n\n"
        f"📝 *{q.title}*\n\n"
        f"📎 *Шпаргалка:*\n```{q.cheat_sheet or 'Нет шпаргалки'}```"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Знаю!", callback_data=f'mark_studied_{q.id}')],
        [InlineKeyboardButton("❌ Пока нет", callback_data=f'next_study_{disc_id}')],
        [InlineKeyboardButton("📝 К списку", callback_data=f'questions_list_{disc_id}')],
        back_button(f'discipline_{disc_id}')
    ]
    
    await query.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=InlineKeyboardMarkup(keyboard))

async def mark_studied(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[2])
    
    session = Session()
    q = session.query(Question).get(q_id)
    q.is_studied = True
    disc_id = q.discipline_id
    
    disc = session.query(Discipline).get(disc_id)
    disc.studied_questions = session.query(Question).filter_by(
        discipline_id=disc_id, 
        is_studied=True
    ).count()
    
    session.commit()
    session.close()
    
    await study_mode(update, context)

async def next_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    await study_mode(update, context)

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 Введи ключевое слово для поиска по шпаргалкам:\n"
        "(ищу по всем дисциплинам)\n\n(или /cancel для отмены)",
        reply_markup=InlineKeyboardMarkup([back_button()])
    )
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_term = update.message.text.lower()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    my_discs = [d.id for d in session.query(Discipline).filter_by(user_id=user.id).all()]
    shared = session.query(SharedAccess).filter_by(user_id=user.id).all()
    shared_discs = [s.discipline_id for s in shared]
    all_discs = my_discs + shared_discs
    
    results = session.query(Question).filter(
        Question.discipline_id.in_(all_discs)
    ).filter(
        (func.lower(Question.title).like(f'%{search_term}%')) |
        (func.lower(Question.cheat_sheet).like(f'%{search_term}%'))
    ).all()
    
    session.close()
    
    if not results:
        await update.message.reply_text(
            "🔍 Ничего не найдено.\n\nПопробуй другое слово:",
            reply_markup=InlineKeyboardMarkup([back_button(), [InlineKeyboardButton("🔍 Новый поиск", callback_data='search_cheatsheets')]])
        )
        return SEARCH_QUERY
    
    text = f"🔍 *Результаты поиска* ({len(results)} найдено):\n\n"
    
    for q in results:
        status = "✅" if q.is_studied else "⬜"
        files_text = f" 📁{len(q.files)}" if q.files else ""
        text += (
            f"{status} *{q.discipline.name}*{files_text}\n"
            f"Вопрос {q.number}: {q.title}\n"
            f"```{q.cheat_sheet[:200]}{'...' if len(q.cheat_sheet) > 200 else ''}```\n\n"
        )
    
    await update.message.reply_text(
        text, 
        parse_mode='MarkdownV2',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Новый поиск", callback_data='search_cheatsheets')],
            back_button()
        ])
    )
    
    return ConversationHandler.END

async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    disciplines = session.query(Discipline).filter_by(user_id=user.id).all()
    session.close()
    
    if not disciplines:
        await query.edit_message_text(
            "📭 Нет данных для статистики.",
            reply_markup=main_menu()
        )
        return
    
    total_q = sum(d.total_questions for d in disciplines)
    studied_q = sum(d.studied_questions for d in disciplines)
    total_progress = (studied_q / total_q * 100) if total_q > 0 else 0
    
    text = (
        f"📊 *Общий прогресс подготовки*\n\n"
        f"📚 Дисциплин: {len(disciplines)}\n"
        f"📝 Всего вопросов: {total_q}\n"
        f"✅ Изучено: {studied_q}\n"
        f"📈 Общий прогресс: {total_progress:.1f}%\n\n"
    )
    
    for disc in disciplines:
        progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
        bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
        text += f"{disc.name}\n[{bar}] {progress:.0f}%\n\n"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=main_menu())

async def disc_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    questions = session.query(Question).filter_by(discipline_id=disc_id).all()
    session.close()
    
    by_diff = {"easy": [0, 0], "medium": [0, 0], "hard": [0, 0]}
    for q in questions:
        by_diff[q.difficulty][0] += 1
        if q.is_studied:
            by_diff[q.difficulty][1] += 1
    
    progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
    bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
    
    text = (
        f"📊 *{disc.name}*\n\n"
        f"[{bar}] {progress:.1f}%\n"
        f"✅ {disc.studied_questions} из {disc.total_questions}\n\n"
        f"По сложности:\n"
        f"🟢 Лёгкие: {by_diff['easy'][1]}/{by_diff['easy'][0]}\n"
        f"🟡 Средние: {by_diff['medium'][1]}/{by_diff['medium'][0]}\n"
        f"🔴 Сложные: {by_diff['hard'][1]}/{by_diff['hard'][0]}\n\n"
    )
    
    if disc.exam_date:
        days_left = (disc.exam_date - datetime.now()).days
        if days_left > 0:
            per_day = (disc.total_questions - disc.studied_questions) / days_left if days_left > 0 else 0
            text += f"📅 До экзамена: {days_left} дней\n"
            text += f"📚 Нужно учить: ~{per_day:.1f} вопроса/день"
        elif days_left == 0:
            text += "📅 Экзамен *сегодня*!"
        else:
            text += "📅 Экзамен уже прошёл"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=discipline_menu(disc_id))

async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    disciplines = session.query(Discipline).filter_by(user_id=user.id).filter(
        Discipline.exam_date != None
    ).order_by(Discipline.exam_date).all()
    session.close()
    
    if not disciplines:
        await query.edit_message_text(
            "📅 Нет запланированных экзаменов.",
            reply_markup=main_menu()
        )
        return
    
    now = datetime.now()
    text = "📅 *Расписание сессии:*\n\n"
    
    for disc in disciplines:
        days_left = (disc.exam_date - now).days
        progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
        
        if days_left > 0:
            time_text = f"через {days_left} дней"
        elif days_left == 0:
            time_text = "*СЕГОДНЯ* 🚨"
        else:
            time_text = f"прошёл ({abs(days_left)} дн. назад)"
        
        bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
        text += (
            f"*{disc.name}*\n"
            f"📆 {disc.exam_date.strftime('%d.%m.%Y')} — {time_text}\n"
            f"[{bar}] {progress:.0f}%\n\n"
        )
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=main_menu())

async def delete_discipline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    name = disc.name
    session.delete(disc)
    session.commit()
    session.close()
    
    await query.edit_message_text(
        f"🗑 Дисциплина \"{name}\" удалена.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 К дисциплинам", callback_data='my_disciplines')],
            back_button()
        ])
    )

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[2])
    
    session = Session()
    q = session.query(Question).get(q_id)
    disc_id = q.discipline_id
    number = q.number
    session.delete(q)
    
    remaining = session.query(Question).filter_by(discipline_id=disc_id).filter(
        Question.number > number
    ).order_by(Question.number).all()
    
    for r in remaining:
        r.number -= 1
    
    disc = session.query(Discipline).get(disc_id)
    disc.total_questions = session.query(Question).filter_by(discipline_id=disc_id).count()
    disc.studied_questions = session.query(Question).filter_by(
        discipline_id=disc_id, 
        is_studied=True
    ).count()
    
    session.commit()
    session.close()
    
    await questions_list(update, context)

async def edit_cheatsheet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_id = int(query.data.split('_')[2])
    context.user_data['edit_q_id'] = q_id
    
    session = Session()
    q = session.query(Question).get(q_id)
    session.close()
    
    await query.edit_message_text(
        f"✏️ Редактирование шпаргалки\n\n"
        f"Текущая шпаргалка:\n```{q.cheat_sheet or 'Пусто'}```\n\n"
        f"Введите новую шпаргалку:\n\n(или /cancel для отмены)",
        parse_mode='MarkdownV2',
        reply_markup=InlineKeyboardMarkup([back_button(f'question_{q_id}')])
    )
    return EDIT_CHEATSHEET

async def save_edited_cheatsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = update.message.text
    q_id = context.user_data['edit_q_id']
    
    session = Session()
    q = session.query(Question).get(q_id)
    q.cheat_sheet = new_text
    disc_id = q.discipline_id
    session.commit()
    session.close()
    
    await update.message.reply_text(
        "✅ Шпаргалка обновлена!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К списку вопросов", callback_data=f'questions_list_{disc_id}')],
            [InlineKeyboardButton("◀️ К дисциплине", callback_data=f'discipline_{disc_id}')],
            back_button()
        ])
    )
    
    return ConversationHandler.END

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙️ *Настройки*\n\n"
        "Управляй напоминаниями, экспортом и совместным доступом:",
        parse_mode='Markdown',
        reply_markup=settings_menu()
    )

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'main_menu':
        await query.edit_message_text("Главное меню:", reply_markup=main_menu())
    elif data == 'settings':
        await settings(update, context)
    elif data == 'reminder_settings':
        await reminder_settings(update, context)
    elif data == 'sharing_menu':
        await sharing_menu(update, context)
    elif data == 'export_menu':
        await export_menu(update, context)
    elif data.startswith('discipline_'):
        await discipline_detail(update, context)
    elif data.startswith('questions_list_'):
        await questions_list(update, context)
    elif data.startswith('question_'):
        await question_detail(update, context)
    elif data.startswith('add_question_'):
        await add_question_start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Отменено.",
        reply_markup=main_menu()
    )
    return ConversationHandler.END
def main():
    TOKEN = os.environ.get("TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
    
    application = Application.builder().token(TOKEN).build()
    
    # Восстанавливаем напоминания при запуске
    session = Session()
    users_with_reminders = session.query(User).filter_by(reminder_enabled=True).all()
    for user in users_with_reminders:
        hour, minute = map(int, user.reminder_time.split(':'))
        application.job_queue.run_daily(
            send_reminder,
            time=datetime.time(hour=hour, minute=minute),
            chat_id=user.telegram_id,
            name=str(user.telegram_id)
        )
    session.close()
    
    # Conversation: добавление дисциплины
    disc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_discipline_start, pattern='^add_discipline$')],
        states={
            DISCIPLINE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_discipline_name)],
            DISCIPLINE_QUESTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_discipline_questions)],
            DISCIPLINE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_discipline_date)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^(main_menu|my_disciplines)$')
        ],
    )
    
    # Conversation: добавление вопроса
    q_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_question_start, pattern='^add_question_')],
        states={
            QUESTION_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_question_title)],
            QUESTION_CHEATSHEET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cheatsheet)],
            QUESTION_DIFFICULTY: [CallbackQueryHandler(get_difficulty, pattern='^diff_')],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^(questions_list_|discipline_)')
        ],
    )
    
    # Conversation: поиск
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_start, pattern='^search_cheatsheets$')],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^main_menu$')
        ],
    )
    
    # Conversation: редактирование шпаргалки
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_cheatsheet_start, pattern='^edit_cheatsheet_')],
        states={
            EDIT_CHEATSHEET: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_cheatsheet)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^question_')
        ],
    )
    
    # Conversation: напоминания
    reminder_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(change_reminder_time_start, pattern='^change_reminder_time$')],
        states={
            REMINDER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reminder_time)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^reminder_settings$')
        ],
    )
    
    # Conversation: присоединение к дисциплине
    join_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(join_discipline_start, pattern='^join_discipline$')],
        states={
            JOIN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, join_discipline_process)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^sharing_menu$')
        ],
    )
    
    # Conversation: добавление файла
    file_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_file_start, pattern='^add_file_')],
        states={
            FILE_UPLOAD: [
                MessageHandler(filters.Document.ALL | filters.PHOTO | filters.AUDIO | filters.VOICE | filters.VIDEO, process_file)
            ],
            FILE_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_file)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(back_handler, pattern='^question_')
        ],
    )
    
    # Основные команды
    application.add_handler(CommandHandler('start', start))
    
    # Conversations
    application.add_handler(disc_conv)
    application.add_handler(q_conv)
    application.add_handler(search_conv)
    application.add_handler(edit_conv)
    application.add_handler(reminder_conv)
    application.add_handler(join_conv)
    application.add_handler(file_conv)
    
    # Самопроверка
    application.add_handler(CallbackQueryHandler(self_check, pattern='^self_check_'))
    application.add_handler(CallbackQueryHandler(check_know, pattern='^check_know$'))
    application.add_handler(CallbackQueryHandler(check_dont_know, pattern='^check_dont_know$'))
    application.add_handler(CallbackQueryHandler(check_next, pattern='^check_next$'))
    application.add_handler(CallbackQueryHandler(check_finish, pattern='^check_finish$'))
    
    # Настройки и экспорт
    application.add_handler(CallbackQueryHandler(settings, pattern='^settings$'))
    application.add_handler(CallbackQueryHandler(reminder_settings, pattern='^reminder_settings$'))
    application.add_handler(CallbackQueryHandler(toggle_reminder, pattern='^toggle_reminder$'))
    application.add_handler(CallbackQueryHandler(sharing_menu, pattern='^sharing_menu$'))
    application.add_handler(CallbackQueryHandler(export_menu, pattern='^export_menu$'))
    application.add_handler(CallbackQueryHandler(export_all_txt, pattern='^export_txt$'))
    application.add_handler(CallbackQueryHandler(export_discipline, pattern='^export_discipline_'))
    application.add_handler(CallbackQueryHandler(share_discipline, pattern='^share_discipline_'))
    application.add_handler(CallbackQueryHandler(unshare_discipline, pattern='^unshare_'))
    
    # Файлы
    application.add_handler(CallbackQueryHandler(view_files, pattern='^view_files_'))
    application.add_handler(CallbackQueryHandler(manage_files, pattern='^manage_files_'))
    application.add_handler(CallbackQueryHandler(delete_file, pattern='^delete_file_'))
    
    # Основная навигация
    application.add_handler(CallbackQueryHandler(my_disciplines, pattern='^my_disciplines$'))
    application.add_handler(CallbackQueryHandler(discipline_detail, pattern='^discipline_'))
    application.add_handler(CallbackQueryHandler(questions_list, pattern='^questions_list_'))
    application.add_handler(CallbackQueryHandler(question_detail, pattern='^question_'))
    application.add_handler(CallbackQueryHandler(study_mode, pattern='^study_mode_'))
    application.add_handler(CallbackQueryHandler(mark_studied, pattern='^mark_studied_'))
    application.add_handler(CallbackQueryHandler(next_study, pattern='^next_study_'))
    application.add_handler(CallbackQueryHandler(show_progress, pattern='^progress$'))
    application.add_handler(CallbackQueryHandler(disc_progress, pattern='^disc_progress_'))
    application.add_handler(CallbackQueryHandler(countdown, pattern='^countdown$'))
    application.add_handler(CallbackQueryHandler(delete_discipline, pattern='^delete_discipline_'))
    application.add_handler(CallbackQueryHandler(delete_question, pattern='^delete_question_'))
    
    # Кнопки "Назад"
    application.add_handler(CallbackQueryHandler(back_handler, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(back_handler, pattern='^settings$'))
    application.add_handler(CallbackQueryHandler(back_handler, pattern='^reminder_settings$'))
    application.add_handler(CallbackQueryHandler(back_handler, pattern='^sharing_menu$'))
    application.add_handler(CallbackQueryHandler(back_handler, pattern='^export_menu$'))
    
    print("🎓 Бот для подготовки к сессии запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
