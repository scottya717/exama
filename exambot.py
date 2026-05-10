import logging
import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
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
    disciplines = relationship("Discipline", back_populates="user", cascade="all, delete-orphan")

class Discipline(Base):
    __tablename__ = 'disciplines'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String, nullable=False)
    total_questions = Column(Integer, default=0)
    studied_questions = Column(Integer, default=0)
    exam_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User", back_populates="disciplines")
    questions = relationship("Question", back_populates="discipline", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = 'questions'
    id = Column(Integer, primary_key=True)
    discipline_id = Column(Integer, ForeignKey('disciplines.id'))
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    cheat_sheet = Column(Text, nullable=True)  # шпаргалка
    is_studied = Column(Boolean, default=False)
    difficulty = Column(String, default='medium')  # easy, medium, hard
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    discipline = relationship("Discipline", back_populates="questions")

Base.metadata.create_all(engine)

# Состояния
(
    DISCIPLINE_NAME, DISCIPLINE_QUESTIONS, DISCIPLINE_DATE,
    QUESTION_SELECT, QUESTION_TITLE, QUESTION_CHEATSHEET, QUESTION_DIFFICULTY,
    EDIT_DISCIPLINE, EDIT_QUESTION, BROWSE_DISCIPLINE, SEARCH_QUERY
) = range(11)

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📚 Мои дисциплины", callback_data='my_disciplines')],
        [InlineKeyboardButton("➕ Добавить дисциплину", callback_data='add_discipline')],
        [InlineKeyboardButton("📊 Прогресс подготовки", callback_data='progress')],
        [InlineKeyboardButton("🔍 Поиск по шпаргалкам", callback_data='search_cheatsheets')],
        [InlineKeyboardButton("📅 До сессии", callback_data='countdown')]
    ]
    return InlineKeyboardMarkup(keyboard)

def discipline_menu(disc_id):
    keyboard = [
        [InlineKeyboardButton("📝 Список вопросов", callback_data=f'questions_list_{disc_id}')],
        [InlineKeyboardButton("➕ Добавить вопрос", callback_data=f'add_question_{disc_id}')],
        [InlineKeyboardButton("📖 Режим заучивания", callback_data=f'study_mode_{disc_id}')],
        [InlineKeyboardButton("📊 Прогресс по дисциплине", callback_data=f'disc_progress_{disc_id}')],
        [InlineKeyboardButton("✏️ Изменить экзамен", callback_data=f'edit_discipline_{disc_id}')],
        [InlineKeyboardButton("🗑 Удалить дисциплину", callback_data=f'delete_discipline_{disc_id}')],
        [InlineKeyboardButton("◀️ Назад", callback_data='my_disciplines')]
    ]
    return InlineKeyboardMarkup(keyboard)

def question_menu(q_id, disc_id):
    keyboard = [
        [InlineKeyboardButton("✅ Отметить изученным", callback_data=f'mark_studied_{q_id}')],
        [InlineKeyboardButton("✏️ Редактировать шпаргалку", callback_data=f'edit_cheatsheet_{q_id}')],
        [InlineKeyboardButton("📝 Изменить вопрос", callback_data=f'edit_question_{q_id}')],
        [InlineKeyboardButton("🗑 Удалить вопрос", callback_data=f'delete_question_{q_id}')],
        [InlineKeyboardButton("◀️ К дисциплине", callback_data=f'questions_list_{disc_id}')]
    ]
    return InlineKeyboardMarkup(keyboard)

def difficulty_keyboard():
    keyboard = [
        [InlineKeyboardButton("🟢 Лёгкий", callback_data='diff_easy')],
        [InlineKeyboardButton("🟡 Средний", callback_data='diff_medium')],
        [InlineKeyboardButton("🔴 Сложный", callback_data='diff_hard')]
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
        "• 📝 Создавать сжатые шпаргалки по каждому вопросу\n"
        "• 📊 Отслеживать прогресс изучения\n"
        "• 🔍 Быстро находить нужную информацию\n\n"
        "Всё хранится в одном месте — твоя личная база знаний!"
    )
    
    await update.message.reply_text(text, reply_markup=main_menu())

async def my_disciplines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    disciplines = session.query(Discipline).filter_by(user_id=user.id).all()
    session.close()
    
    if not disciplines:
        await query.edit_message_text(
            "📭 У тебя пока нет дисциплин.\n\nДобавь первую:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Добавить дисциплину", callback_data='add_discipline')
            ], [InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]])
        )
        return
    
    text = "📚 *Твои дисциплины:*\n\n"
    keyboard = []
    
    for disc in disciplines:
        progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
        exam_text = f" (экзамен: {disc.exam_date.strftime('%d.%m')})" if disc.exam_date else ""
        text += f"• *{disc.name}*{exam_text}\n"
        text += f"  Прогресс: {disc.studied_questions}/{disc.total_questions} ({progress:.0f}%)\n\n"
        keyboard.append([InlineKeyboardButton(
            f"{disc.name} ({disc.studied_questions}/{disc.total_questions})", 
            callback_data=f'discipline_{disc.id}'
        )])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='main_menu')])
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def discipline_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[1])
    
    session = Session()
    disc = session.query(Discipline).get(disc_id)
    session.close()
    
    if not disc:
        await query.edit_message_text("❌ Дисциплина не найдена", reply_markup=main_menu())
        return
    
    progress = (disc.studied_questions / disc.total_questions * 100) if disc.total_questions > 0 else 0
    exam_text = f"\n📅 Экзамен: *{disc.exam_date.strftime('%d.%m.%Y')}*" if disc.exam_date else ""
    
    text = (
        f"📖 *{disc.name}*\n"
        f"📝 Всего вопросов: {disc.total_questions}\n"
        f"✅ Изучено: {disc.studied_questions}\n"
        f"📊 Прогресс: {progress:.1f}%{exam_text}"
    )
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=discipline_menu(disc_id))

# Добавление дисциплины
async def add_discipline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📚 Введите название дисциплины:")
    return DISCIPLINE_NAME

async def get_discipline_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['disc_name'] = update.message.text
    await update.message.reply_text("🔢 Сколько вопросов (билетов) в этой дисциплине?")
    return DISCIPLINE_QUESTIONS

async def get_discipline_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text)
        if count <= 0:
            raise ValueError
        context.user_data['disc_questions'] = count
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число:")
        return DISCIPLINE_QUESTIONS
    
    await update.message.reply_text(
        "📅 Введите дату экзамена в формате ДД.ММ.ГГГГ\n"
        "(или отправьте '-' если дата неизвестна):"
    )
    return DISCIPLINE_DATE

async def get_discipline_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    exam_date = None
    
    if text != '-':
        try:
            exam_date = datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await update.message.reply_text("❌ Неверный формат! Попробуйте снова (ДД.ММ.ГГГГ):")
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
    
    await update.message.reply_text(
        f"✅ Дисциплина добавлена!\n\n"
        f"📖 *{context.user_data['disc_name']}*{date_text}\n"
        f"📝 Вопросов: {context.user_data['disc_questions']}\n\n"
        f"Теперь добавь вопросы и шпаргалки:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Добавить вопросы", callback_data=f'add_question_{disc_id}')
        ], [InlineKeyboardButton("📚 К дисциплинам", callback_data='my_disciplines')]])
    )
    
    return ConversationHandler.END

# Вопросы
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
            text += f"{status} *Вопрос {q.number}*: {q.title} {has_cheat} {diff_emoji[q.difficulty]}\n"
            keyboard.append([InlineKeyboardButton(
                f"{status} Вопрос {q.number}: {q.title[:30]}{'...' if len(q.title) > 30 else ''}",
                callback_data=f'question_{q.id}'
            )])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить вопрос", callback_data=f'add_question_{disc_id}')])
    keyboard.append([InlineKeyboardButton("◀️ К дисциплине", callback_data=f'discipline_{disc_id}')])
    
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
    
    text = (
        f"📝 *Вопрос {q.number}*\n"
        f"*{q.title}*\n\n"
        f"📊 Сложность: {diff_emoji[q.difficulty]}\n"
        f"📋 Статус: {status}\n\n"
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
        f"Введите название/формулировку вопроса:",
        parse_mode='Markdown'
    )
    return QUESTION_TITLE

async def get_question_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['q_title'] = update.message.text
    await update.message.reply_text(
        "📝 Введите сжатую шпаргалку по этому вопросу.\n"
        "Советы для хорошей шпаргалки:\n"
        "• Используй ключевые слова и формулы\n"
        "• Структурируй пунктами\n"
        "• Выдели главное, убери воду\n\n"
        "Отправь текст шпаргалки:"
    )
    return QUESTION_CHEATSHEET

async def get_cheatsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['q_cheatsheet'] = update.message.text
    await update.message.reply_text(
        "Выберите сложность вопроса:",
        reply_markup=difficulty_keyboard()
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
    session.commit()
    session.close()
    
    diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
    
    await query.edit_message_text(
        f"✅ Вопрос добавлен!\n\n"
        f"📝 *Вопрос {context.user_data['next_number']}*\n"
        f"{context.user_data['q_title']}\n\n"
        f"📎 Шпаргалка сохранена\n"
        f"Сложность: {diff_emoji[difficulty]}\n\n"
        f"Что дальше?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Ещё вопрос", callback_data=f'add_question_{disc_id}')],
            [InlineKeyboardButton("📋 Список вопросов", callback_data=f'questions_list_{disc_id}')],
            [InlineKeyboardButton("📚 К дисциплинам", callback_data='my_disciplines')]
        ])
    )
    
    return ConversationHandler.END

# Режим заучивания
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
        await query.edit_message_text(
            "🎉 Все вопросы изучены! Отличная работа!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ К дисциплине", callback_data=f'discipline_{disc_id}')
            ]])
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
        [InlineKeyboardButton("◀️ Выход", callback_data=f'discipline_{disc_id}')]
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
    
    # Продолжаем заучивание
    await study_mode(update, context)

async def next_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disc_id = int(query.data.split('_')[2])
    
    # Показываем следующий вопрос
    await study_mode(update, context)

# Поиск
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 Введи ключевое слово для поиска по шпаргалкам:\n"
        "(ищу по всем дисциплинам)"
    )
    return SEARCH_QUERY

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_term = update.message.text.lower()
    
    session = Session()
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    
    results = session.query(Question).join(Discipline).filter(
        Discipline.user_id == user.id
    ).filter(
        (func.lower(Question.title).like(f'%{search_term}%')) |
        (func.lower(Question.cheat_sheet).like(f'%{search_term}%'))
    ).all()
    
    session.close()
    
    if not results:
        await update.message.reply_text(
            "🔍 Ничего не найдено.\n\nПопробуй другое слово:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data='main_menu')
            ]])
        )
        return SEARCH_QUERY
    
    text = f"🔍 *Результаты поиска* ({len(results)} найдено):\n\n"
    
    for q in results:
        status = "✅" if q.is_studied else "⬜"
        text += (
            f"{status} *{q.discipline.name}*\n"
            f"Вопрос {q.number}: {q.title}\n"
            f"```{q.cheat_sheet[:200]}{'...' if len(q.cheat_sheet) > 200 else ''}```\n\n"
        )
    
    await update.message.reply_text(
        text, 
        parse_mode='MarkdownV2',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Назад", callback_data='main_menu')
        ]])
    )
    
    return ConversationHandler.END

# Прогресс
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

# Обратный отсчёт
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

# Удаление
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
        reply_markup=main_menu()
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
    
    # Перенумеровываем оставшиеся
    remaining = session.query(Question).filter_by(discipline_id=disc_id).filter(
        Question.number > number
    ).order_by(Question.number).all()
    
    for r in remaining:
        r.number -= 1
    
    # Обновляем счётчики
    disc = session.query(Discipline).get(disc_id)
    disc.total_questions = session.query(Question).filter_by(discipline_id=disc_id).count()
    disc.studied_questions = session.query(Question).filter_by(
        discipline_id=disc_id, 
        is_studied=True
    ).count()
    
    session.commit()
    session.close()
    
    # Возвращаемся к списку
    await questions_list(update, context)

# Редактирование шпаргалки
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
        f"Введите новую шпаргалку:",
        parse_mode='MarkdownV2'
    )
    return EDIT_QUESTION

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
            [InlineKeyboardButton("◀️ К дисциплине", callback_data=f'discipline_{disc_id}')]
        ])
    )
    
    return ConversationHandler.END

# Навигация
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Главное меню:", reply_markup=main_menu())

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=main_menu())
    return ConversationHandler.END

def main():
    TOKEN = os.environ.get("TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
    
    application = Application.builder().token(TOKEN).build()
    
    # Conversation: добавление дисциплины
    disc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_discipline_start, pattern='^add_discipline$')],
        states={
            DISCIPLINE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_discipline_name)],
            DISCIPLINE_QUESTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_discipline_questions)],
            DISCIPLINE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_discipline_date)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Conversation: добавление вопроса
    q_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_question_start, pattern='^add_question_')],
        states={
            QUESTION_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_question_title)],
            QUESTION_CHEATSHEET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cheatsheet)],
            QUESTION_DIFFICULTY: [CallbackQueryHandler(get_difficulty, pattern='^diff_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Conversation: поиск
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_start, pattern='^search_cheatsheets$')],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_search)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Conversation: редактирование шпаргалки
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_cheatsheet_start, pattern='^edit_cheatsheet_')],
        states={
            EDIT_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_cheatsheet)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(disc_conv)
    application.add_handler(q_conv)
    application.add_handler(search_conv)
    application.add_handler(edit_conv)
    
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
    application.add_handler(CallbackQueryHandler(back_to_main, pattern='^main_menu$'))
    
    print("🎓 Бот для подготовки к сессии запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
