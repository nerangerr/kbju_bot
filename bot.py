import os
import logging
import requests
import urllib.parse
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Загружаем переменные из .env
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID', 0))
EDAMAM_APP_ID = os.getenv('EDAMAM_APP_ID', '')
EDAMAM_APP_KEY = os.getenv('EDAMAM_APP_KEY', '')

# Настройка базы данных
engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)
session = Session()

# --- Модели базы данных ---
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String)
    first_name = Column(String)
    sex = Column(String)
    age = Column(Integer)
    height = Column(Float)
    weight = Column(Float)
    activity_level = Column(String)
    goal = Column(String)
    daily_calories = Column(Integer)
    daily_protein = Column(Float, default=0)
    daily_fat = Column(Float, default=0)
    daily_carbs = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now)

class Meal(Base):
    __tablename__ = 'meals'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    product_name = Column(String)
    weight = Column(Float)
    cooking_method = Column(String)
    calories = Column(Float)
    protein = Column(Float, default=0)
    fat = Column(Float, default=0)
    carbs = Column(Float, default=0)
    meal_time = Column(DateTime, default=datetime.now)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    calories = Column(Float, nullable=False)
    protein = Column(Float, default=0)
    fat = Column(Float, default=0)
    carbs = Column(Float, default=0)
    source = Column(String, default='manual')
    created_at = Column(DateTime, default=datetime.now)

class Water(Base):
    __tablename__ = 'water'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    amount = Column(Float)  # в мл
    created_at = Column(DateTime, default=datetime.now)

class DailyPlan(Base):
    __tablename__ = 'daily_plans'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    plan_date = Column(DateTime, default=datetime.now)
    meals = Column(Text)          # JSON с планом
    total_calories = Column(Integer)
    target_calories = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)

# --- НОВАЯ ТАБЛИЦА ДЛЯ ИСТОРИИ ВЕСА ---
class WeightEntry(Base):
    __tablename__ = 'weight_entries'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    weight = Column(Float)  # в кг, с точностью до граммов (например, 58.050)
    created_at = Column(DateTime, default=datetime.now)

# Создаем таблицы
Base.metadata.create_all(engine)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# --- ГЛАВНОЕ МЕНЮ (КЛАВИАТУРА) ---
def main_menu_keyboard():
    """Создаёт клавиатуру главного меню"""
    keyboard = [
        [
            InlineKeyboardButton("🍽 Добавить еду", callback_data='menu_add_food'),
            InlineKeyboardButton("💧 Вода", callback_data='menu_water')
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data='menu_stats'),
            InlineKeyboardButton("📋 Мои приёмы", callback_data='menu_my_food')
        ],
        [
            InlineKeyboardButton("📅 План на завтра", callback_data='menu_plan'),
            InlineKeyboardButton("📜 История приёмов", callback_data='menu_history')
        ],
        [
            InlineKeyboardButton("⚖️ Вес/Прогресс", callback_data='menu_weight'),
            InlineKeyboardButton("⚙️ Профиль", callback_data='menu_profile')
        ],
        [
            InlineKeyboardButton("❓ Помощь", callback_data='menu_help')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- СТАТИЧЕСКАЯ БАЗА ПРОДУКТОВ (полная, как у тебя) ---
PRODUCTS_DB = {
    # === КРУПЫ ===
    'гречка': {'calories': 330, 'protein': 12.6, 'fat': 3.3, 'carbs': 62.1, 'category': 'grain'},
    'рис': {'calories': 350, 'protein': 7.5, 'fat': 0.5, 'carbs': 78.0, 'category': 'grain'},
    'овсянка': {'calories': 350, 'protein': 12.0, 'fat': 6.0, 'carbs': 62.0, 'category': 'grain'},
    'макароны': {'calories': 350, 'protein': 13.0, 'fat': 1.5, 'carbs': 70.0, 'category': 'grain'},
    
    # === МЯСО ===
    'курица': {'calories': 110, 'protein': 23.0, 'fat': 1.5, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.67},
    'куриная грудка': {'calories': 110, 'protein': 23.0, 'fat': 1.5, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.67},
    'куриное филе': {'calories': 110, 'protein': 23.0, 'fat': 1.5, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.67},
    'куриные голени': {'calories': 160, 'protein': 20.0, 'fat': 8.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.67},
    'куриные бедра': {'calories': 180, 'protein': 18.0, 'fat': 12.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.67},
    'куриные крылья': {'calories': 200, 'protein': 16.0, 'fat': 15.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.67},
    'индейка': {'calories': 135, 'protein': 22.0, 'fat': 5.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.7},
    'говядина': {'calories': 250, 'protein': 26.0, 'fat': 16.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.7},
    'говяжий фарш': {'calories': 280, 'protein': 25.0, 'fat': 20.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.7},
    'свинина': {'calories': 300, 'protein': 20.0, 'fat': 25.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.75},
    'баранина': {'calories': 280, 'protein': 22.0, 'fat': 22.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.7},
    'конина': {'calories': 143, 'protein': 20.0, 'fat': 6.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.6},
    
    # === РЫБА ===
    'рыба': {'calories': 150, 'protein': 20.0, 'fat': 7.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.8},
    'лосось': {'calories': 220, 'protein': 22.0, 'fat': 15.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.8},
    'семга': {'calories': 220, 'protein': 22.0, 'fat': 15.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.8},
    'тунец': {'calories': 130, 'protein': 26.0, 'fat': 3.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.8},
    'треска': {'calories': 80, 'protein': 18.0, 'fat': 0.5, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.8},
    'скумбрия': {'calories': 230, 'protein': 20.0, 'fat': 15.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.8},
    
    # === ФРУКТЫ ===
    'яблоко': {'calories': 52, 'protein': 0.3, 'fat': 0.2, 'carbs': 14.0, 'category': 'fruit'},
    'груша': {'calories': 57, 'protein': 0.4, 'fat': 0.1, 'carbs': 15.0, 'category': 'fruit'},
    'банан': {'calories': 89, 'protein': 1.1, 'fat': 0.3, 'carbs': 23.0, 'category': 'fruit'},
    'апельсин': {'calories': 47, 'protein': 0.9, 'fat': 0.1, 'carbs': 12.0, 'category': 'fruit'},
    'манго': {'calories': 60, 'protein': 0.8, 'fat': 0.4, 'carbs': 15.0, 'category': 'fruit'},
    'киви': {'calories': 61, 'protein': 1.1, 'fat': 0.5, 'carbs': 15.0, 'category': 'fruit'},
    'виноград': {'calories': 69, 'protein': 0.7, 'fat': 0.2, 'carbs': 18.0, 'category': 'fruit'},
    'клубника': {'calories': 32, 'protein': 0.7, 'fat': 0.3, 'carbs': 8.0, 'category': 'fruit'},
    'малина': {'calories': 52, 'protein': 1.2, 'fat': 0.7, 'carbs': 12.0, 'category': 'fruit'},
    'вишня': {'calories': 50, 'protein': 1.0, 'fat': 0.3, 'carbs': 12.0, 'category': 'fruit'},
    'персик': {'calories': 39, 'protein': 0.9, 'fat': 0.3, 'carbs': 10.0, 'category': 'fruit'},
    'абрикос': {'calories': 48, 'protein': 1.4, 'fat': 0.4, 'carbs': 11.0, 'category': 'fruit'},
    'слива': {'calories': 46, 'protein': 0.7, 'fat': 0.3, 'carbs': 11.0, 'category': 'fruit'},
    'лимон': {'calories': 29, 'protein': 1.1, 'fat': 0.3, 'carbs': 9.0, 'category': 'fruit'},
    'лайм': {'calories': 30, 'protein': 0.7, 'fat': 0.2, 'carbs': 11.0, 'category': 'fruit'},
    'грейпфрут': {'calories': 42, 'protein': 0.8, 'fat': 0.1, 'carbs': 11.0, 'category': 'fruit'},
    'гранат': {'calories': 83, 'protein': 1.7, 'fat': 1.2, 'carbs': 19.0, 'category': 'fruit'},
    'хурма': {'calories': 127, 'protein': 0.6, 'fat': 0.4, 'carbs': 34.0, 'category': 'fruit'},
    'инжир': {'calories': 74, 'protein': 0.8, 'fat': 0.3, 'carbs': 19.0, 'category': 'fruit'},
    'финик': {'calories': 282, 'protein': 2.5, 'fat': 0.4, 'carbs': 75.0, 'category': 'fruit'},
    'ананас': {'calories': 50, 'protein': 0.5, 'fat': 0.1, 'carbs': 13.0, 'category': 'fruit'},
    'арбуз': {'calories': 30, 'protein': 0.6, 'fat': 0.2, 'carbs': 7.6, 'category': 'fruit'},
    'дыня': {'calories': 34, 'protein': 0.8, 'fat': 0.2, 'carbs': 8.0, 'category': 'fruit'},
    'авокадо': {'calories': 160, 'protein': 2.0, 'fat': 15.0, 'carbs': 9.0, 'category': 'fruit'},
    
    # === ОВОЩИ ===
    'картошка': {'calories': 77, 'protein': 2.0, 'fat': 0.1, 'carbs': 17.0, 'category': 'vegetable'},
    'картофель': {'calories': 77, 'protein': 2.0, 'fat': 0.1, 'carbs': 17.0, 'category': 'vegetable'},
    'морковь': {'calories': 41, 'protein': 0.9, 'fat': 0.1, 'carbs': 10.0, 'category': 'vegetable'},
    'капуста': {'calories': 25, 'protein': 1.3, 'fat': 0.1, 'carbs': 5.0, 'category': 'vegetable'},
    'помидор': {'calories': 18, 'protein': 0.9, 'fat': 0.2, 'carbs': 4.0, 'category': 'vegetable'},
    'огурец': {'calories': 15, 'protein': 0.7, 'fat': 0.1, 'carbs': 3.0, 'category': 'vegetable'},
    'свекла': {'calories': 43, 'protein': 1.6, 'fat': 0.2, 'carbs': 10.0, 'category': 'vegetable'},
    'редис': {'calories': 16, 'protein': 0.7, 'fat': 0.1, 'carbs': 3.4, 'category': 'vegetable'},
    'репа': {'calories': 28, 'protein': 0.9, 'fat': 0.1, 'carbs': 6.0, 'category': 'vegetable'},
    'кабачок': {'calories': 17, 'protein': 1.2, 'fat': 0.3, 'carbs': 3.1, 'category': 'vegetable'},
    'баклажан': {'calories': 25, 'protein': 1.0, 'fat': 0.2, 'carbs': 6.0, 'category': 'vegetable'},
    'перец': {'calories': 26, 'protein': 1.0, 'fat': 0.3, 'carbs': 6.0, 'category': 'vegetable'},
    'лук': {'calories': 40, 'protein': 1.1, 'fat': 0.1, 'carbs': 9.0, 'category': 'vegetable'},
    'чеснок': {'calories': 149, 'protein': 6.4, 'fat': 0.5, 'carbs': 33.0, 'category': 'vegetable'},
    'брокколи': {'calories': 34, 'protein': 2.8, 'fat': 0.4, 'carbs': 7.0, 'category': 'vegetable'},
    'цветная капуста': {'calories': 25, 'protein': 1.9, 'fat': 0.3, 'carbs': 5.0, 'category': 'vegetable'},
    
    # === ЯЙЦА И МОЛОЧКА ===
    'яйцо': {'calories': 155, 'protein': 13.0, 'fat': 11.0, 'carbs': 0.5, 'category': 'egg'},
    'яйца': {'calories': 155, 'protein': 13.0, 'fat': 11.0, 'carbs': 0.5, 'category': 'egg'},
    'творог': {'calories': 120, 'protein': 18.0, 'fat': 5.0, 'carbs': 3.0, 'category': 'dairy'},
    'молоко': {'calories': 60, 'protein': 3.3, 'fat': 3.6, 'carbs': 4.8, 'category': 'dairy'},
    'кефир': {'calories': 55, 'protein': 3.4, 'fat': 2.0, 'carbs': 4.0, 'category': 'dairy'},
    'йогурт': {'calories': 70, 'protein': 3.5, 'fat': 2.5, 'carbs': 8.0, 'category': 'dairy'},
    'сыр': {'calories': 350, 'protein': 25.0, 'fat': 28.0, 'carbs': 0.0, 'category': 'dairy'},
    'курт': {'calories': 300, 'protein': 25.0, 'fat': 15.0, 'carbs': 10.0, 'category': 'dairy'},
    
    # === НАЦИОНАЛЬНЫЕ БЛЮДА ===
    'плов': {'calories': 220, 'protein': 8.0, 'fat': 10.0, 'carbs': 25.0, 'category': 'dish'},
    'борщ': {'calories': 60, 'protein': 2.5, 'fat': 2.0, 'carbs': 8.0, 'category': 'dish'},
    'суп': {'calories': 50, 'protein': 2.0, 'fat': 1.5, 'carbs': 7.0, 'category': 'dish'},
    'кумыс': {'calories': 50, 'protein': 2.0, 'fat': 1.0, 'carbs': 5.0, 'category': 'drink'},
    'бешбармак': {'calories': 250, 'protein': 12.0, 'fat': 18.0, 'carbs': 8.0, 'category': 'dish'},
    'баурсак': {'calories': 450, 'protein': 8.0, 'fat': 25.0, 'carbs': 40.0, 'category': 'dish'},
    'шубат': {'calories': 45, 'protein': 2.5, 'fat': 2.0, 'carbs': 4.0, 'category': 'drink'},
    'казы': {'calories': 350, 'protein': 22.0, 'fat': 30.0, 'carbs': 0.0, 'category': 'meat', 'boiled_factor': 0.7},
    
    # === НАПИТКИ ===
    'кофе': {'calories': 35, 'protein': 0.8, 'fat': 0.5, 'carbs': 6.5, 'category': 'drink'},
    'кофе черный': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'черный кофе': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'американо': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'эспрессо': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'кофе без сахара': {'calories': 15, 'protein': 0.8, 'fat': 0.5, 'carbs': 1.5, 'category': 'drink'},
    'кофе без молока': {'calories': 22, 'protein': 0.1, 'fat': 0.0, 'carbs': 5.0, 'category': 'drink'},
    'кофе без молока и сахара': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'кофе с молоком': {'calories': 15, 'protein': 0.8, 'fat': 0.5, 'carbs': 1.5, 'category': 'drink'},
    'кофе с сахаром': {'calories': 22, 'protein': 0.1, 'fat': 0.0, 'carbs': 5.0, 'category': 'drink'},
    'кофе с молоком и сахаром': {'calories': 35, 'protein': 0.8, 'fat': 0.5, 'carbs': 6.5, 'category': 'drink'},
    'латте': {'calories': 15, 'protein': 0.8, 'fat': 0.5, 'carbs': 1.5, 'category': 'drink'},
    'капучино': {'calories': 15, 'protein': 0.8, 'fat': 0.5, 'carbs': 1.5, 'category': 'drink'},
    'чай': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'чай черный': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'черный чай': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'зеленый чай': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'чай с молоком': {'calories': 15, 'protein': 0.8, 'fat': 0.5, 'carbs': 1.5, 'category': 'drink'},
    'чай с сахаром': {'calories': 22, 'protein': 0.1, 'fat': 0.0, 'carbs': 5.0, 'category': 'drink'},
    'чай с молоком и сахаром': {'calories': 35, 'protein': 0.8, 'fat': 0.5, 'carbs': 6.5, 'category': 'drink'},
    'чай без сахара': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'чай без молока': {'calories': 2, 'protein': 0.1, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'какао': {'calories': 40, 'protein': 3.0, 'fat': 2.0, 'carbs': 6.0, 'category': 'drink'},
    'какао с молоком': {'calories': 55, 'protein': 4.0, 'fat': 3.0, 'carbs': 7.0, 'category': 'drink'},
    'какао с сахаром': {'calories': 60, 'protein': 3.0, 'fat': 2.0, 'carbs': 11.0, 'category': 'drink'},
    'какао с молоком и сахаром': {'calories': 75, 'protein': 4.0, 'fat': 3.0, 'carbs': 12.0, 'category': 'drink'},
    'матча': {'calories': 3, 'protein': 0.5, 'fat': 0.0, 'carbs': 0.5, 'category': 'drink'},
    'матча латте': {'calories': 20, 'protein': 1.0, 'fat': 0.5, 'carbs': 2.0, 'category': 'drink'},
    
    # === АЛКОГОЛЬ ===
    'пиво': {'calories': 45, 'protein': 0.5, 'fat': 0.0, 'carbs': 3.5, 'category': 'drink'},
    'пиво светлое': {'calories': 45, 'protein': 0.5, 'fat': 0.0, 'carbs': 3.5, 'category': 'drink'},
    'пиво темное': {'calories': 55, 'protein': 0.6, 'fat': 0.0, 'carbs': 4.5, 'category': 'drink'},
    'пиво безалкогольное': {'calories': 25, 'protein': 0.3, 'fat': 0.0, 'carbs': 5.0, 'category': 'drink'},
    'живое пиво': {'calories': 50, 'protein': 0.5, 'fat': 0.0, 'carbs': 4.0, 'category': 'drink'},
    'крафтовое пиво': {'calories': 60, 'protein': 0.6, 'fat': 0.0, 'carbs': 5.0, 'category': 'drink'},
    
    'водка': {'calories': 235, 'protein': 0.0, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'вино': {'calories': 85, 'protein': 0.1, 'fat': 0.0, 'carbs': 2.5, 'category': 'drink'},
    'вино красное': {'calories': 85, 'protein': 0.1, 'fat': 0.0, 'carbs': 2.5, 'category': 'drink'},
    'вино белое': {'calories': 82, 'protein': 0.1, 'fat': 0.0, 'carbs': 2.0, 'category': 'drink'},
    'вино розовое': {'calories': 83, 'protein': 0.1, 'fat': 0.0, 'carbs': 2.2, 'category': 'drink'},
    'игристое вино': {'calories': 90, 'protein': 0.1, 'fat': 0.0, 'carbs': 3.0, 'category': 'drink'},
    'шампанское': {'calories': 90, 'protein': 0.1, 'fat': 0.0, 'carbs': 3.0, 'category': 'drink'},
    
    'коньяк': {'calories': 240, 'protein': 0.0, 'fat': 0.0, 'carbs': 0.5, 'category': 'drink'},
    'виски': {'calories': 250, 'protein': 0.0, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'ром': {'calories': 230, 'protein': 0.0, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'джин': {'calories': 230, 'protein': 0.0, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'текила': {'calories': 240, 'protein': 0.0, 'fat': 0.0, 'carbs': 0.0, 'category': 'drink'},
    'ликер': {'calories': 300, 'protein': 0.0, 'fat': 0.0, 'carbs': 25.0, 'category': 'drink'},
    'мартини': {'calories': 150, 'protein': 0.0, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'вермут': {'calories': 150, 'protein': 0.0, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'портвейн': {'calories': 160, 'protein': 0.0, 'fat': 0.0, 'carbs': 12.0, 'category': 'drink'},
    'херес': {'calories': 140, 'protein': 0.0, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'саке': {'calories': 130, 'protein': 0.5, 'fat': 0.0, 'carbs': 8.0, 'category': 'drink'},
    'сидр': {'calories': 55, 'protein': 0.1, 'fat': 0.0, 'carbs': 5.0, 'category': 'drink'},
    
    # === АЛКОГОЛЬНЫЕ КОКТЕЙЛИ ===
    'коктейль': {'calories': 200, 'protein': 0.5, 'fat': 0.5, 'carbs': 15.0, 'category': 'drink'},
    'мохито': {'calories': 150, 'protein': 0.2, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    'пина колада': {'calories': 350, 'protein': 0.5, 'fat': 5.0, 'carbs': 30.0, 'category': 'drink'},
    'маргарита': {'calories': 180, 'protein': 0.2, 'fat': 0.0, 'carbs': 12.0, 'category': 'drink'},
    'длинный айленд': {'calories': 280, 'protein': 0.1, 'fat': 0.0, 'carbs': 20.0, 'category': 'drink'},
    'кровавая мэри': {'calories': 120, 'protein': 1.0, 'fat': 0.0, 'carbs': 8.0, 'category': 'drink'},
    'дайкири': {'calories': 170, 'protein': 0.2, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    'космополитен': {'calories': 200, 'protein': 0.2, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    'манхэттен': {'calories': 250, 'protein': 0.1, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'негрони': {'calories': 220, 'protein': 0.1, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'эспрессо мартини': {'calories': 200, 'protein': 1.0, 'fat': 0.5, 'carbs': 15.0, 'category': 'drink'},
    'секс на пляже': {'calories': 180, 'protein': 0.2, 'fat': 0.0, 'carbs': 18.0, 'category': 'drink'},
    'голубая лагуна': {'calories': 160, 'protein': 0.1, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    'темный шторм': {'calories': 200, 'protein': 0.1, 'fat': 0.0, 'carbs': 12.0, 'category': 'drink'},
    'том коллинз': {'calories': 140, 'protein': 0.2, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    'джин тоник': {'calories': 130, 'protein': 0.1, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'водка тоник': {'calories': 130, 'protein': 0.1, 'fat': 0.0, 'carbs': 10.0, 'category': 'drink'},
    'ром кола': {'calories': 150, 'protein': 0.1, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    'виски кола': {'calories': 150, 'protein': 0.1, 'fat': 0.0, 'carbs': 15.0, 'category': 'drink'},
    
    # === БУРГЕРЫ И ФАСТФУД ===
    'бургер': {'calories': 300, 'protein': 15.0, 'fat': 12.0, 'carbs': 30.0, 'category': 'dish'},
    'гамбургер': {'calories': 250, 'protein': 12.0, 'fat': 10.0, 'carbs': 28.0, 'category': 'dish'},
    'чизбургер': {'calories': 300, 'protein': 15.0, 'fat': 14.0, 'carbs': 30.0, 'category': 'dish'},
    'двойной чизбургер': {'calories': 450, 'protein': 25.0, 'fat': 22.0, 'carbs': 35.0, 'category': 'dish'},
    'биг мак': {'calories': 540, 'protein': 25.0, 'fat': 28.0, 'carbs': 45.0, 'category': 'dish'},
    'воппер': {'calories': 650, 'protein': 30.0, 'fat': 35.0, 'carbs': 50.0, 'category': 'dish'},
    'бургер с курицей': {'calories': 350, 'protein': 20.0, 'fat': 12.0, 'carbs': 35.0, 'category': 'dish'},
    'бургер с рыбой': {'calories': 400, 'protein': 18.0, 'fat': 18.0, 'carbs': 35.0, 'category': 'dish'},
    'вегетарианский бургер': {'calories': 280, 'protein': 10.0, 'fat': 8.0, 'carbs': 35.0, 'category': 'dish'},
    'слайдеры': {'calories': 200, 'protein': 10.0, 'fat': 8.0, 'carbs': 20.0, 'category': 'dish'},
    
    # === КАРТОШКА ФРИ И ЗАКУСКИ ===
    'картошка фри': {'calories': 300, 'protein': 3.5, 'fat': 15.0, 'carbs': 40.0, 'category': 'dish'},
    'фри': {'calories': 300, 'protein': 3.5, 'fat': 15.0, 'carbs': 40.0, 'category': 'dish'},
    'картофель фри': {'calories': 300, 'protein': 3.5, 'fat': 15.0, 'carbs': 40.0, 'category': 'dish'},
    'наггетсы': {'calories': 280, 'protein': 15.0, 'fat': 18.0, 'carbs': 15.0, 'category': 'dish'},
    'куриные наггетсы': {'calories': 280, 'protein': 15.0, 'fat': 18.0, 'carbs': 15.0, 'category': 'dish'},
    'стрипсы': {'calories': 260, 'protein': 18.0, 'fat': 14.0, 'carbs': 15.0, 'category': 'dish'},
    'луковые кольца': {'calories': 350, 'protein': 5.0, 'fat': 20.0, 'carbs': 35.0, 'category': 'dish'},
    'чесночные кольца': {'calories': 350, 'protein': 5.0, 'fat': 20.0, 'carbs': 35.0, 'category': 'dish'},
    'чипсы': {'calories': 520, 'protein': 6.0, 'fat': 30.0, 'carbs': 50.0, 'category': 'dish'},
    'картофельные чипсы': {'calories': 520, 'protein': 6.0, 'fat': 30.0, 'carbs': 50.0, 'category': 'dish'},
    'крокеты': {'calories': 280, 'protein': 5.0, 'fat': 15.0, 'carbs': 30.0, 'category': 'dish'},
    
    # === ПИЦЦА ===
    'пицца': {'calories': 280, 'protein': 12.0, 'fat': 10.0, 'carbs': 35.0, 'category': 'dish'},
    'пицца маргарита': {'calories': 250, 'protein': 10.0, 'fat': 8.0, 'carbs': 35.0, 'category': 'dish'},
    'пицца пепперони': {'calories': 320, 'protein': 14.0, 'fat': 14.0, 'carbs': 35.0, 'category': 'dish'},
    'пицца гавайская': {'calories': 280, 'protein': 12.0, 'fat': 9.0, 'carbs': 38.0, 'category': 'dish'},
    'пицца мясная': {'calories': 350, 'protein': 16.0, 'fat': 16.0, 'carbs': 36.0, 'category': 'dish'},
    'пицца с грибами': {'calories': 260, 'protein': 11.0, 'fat': 8.0, 'carbs': 36.0, 'category': 'dish'},
    'пицца 4 сыра': {'calories': 300, 'protein': 13.0, 'fat': 12.0, 'carbs': 34.0, 'category': 'dish'},
    'пицца дьябло': {'calories': 330, 'protein': 14.0, 'fat': 14.0, 'carbs': 35.0, 'category': 'dish'},
    'пицца вегетарианская': {'calories': 240, 'protein': 9.0, 'fat': 7.0, 'carbs': 36.0, 'category': 'dish'},
    'пицца с морепродуктами': {'calories': 270, 'protein': 15.0, 'fat': 8.0, 'carbs': 34.0, 'category': 'dish'},
    'пицца карбонара': {'calories': 310, 'protein': 14.0, 'fat': 12.0, 'carbs': 35.0, 'category': 'dish'},
    'кальцоне': {'calories': 350, 'protein': 16.0, 'fat': 15.0, 'carbs': 40.0, 'category': 'dish'},
    'пицца фокачча': {'calories': 220, 'protein': 8.0, 'fat': 6.0, 'carbs': 35.0, 'category': 'dish'},
    
    # === СУШИ И РОЛЛЫ ===
    'суши': {'calories': 150, 'protein': 6.0, 'fat': 1.0, 'carbs': 30.0, 'category': 'dish'},
    'суши лосось': {'calories': 160, 'protein': 7.0, 'fat': 2.0, 'carbs': 28.0, 'category': 'dish'},
    'суши тунец': {'calories': 150, 'protein': 7.0, 'fat': 1.0, 'carbs': 28.0, 'category': 'dish'},
    'суши угорь': {'calories': 180, 'protein': 7.0, 'fat': 3.0, 'carbs': 30.0, 'category': 'dish'},
    'суши креветка': {'calories': 140, 'protein': 6.0, 'fat': 1.0, 'carbs': 28.0, 'category': 'dish'},
    'суши скумбрия': {'calories': 160, 'protein': 7.0, 'fat': 2.0, 'carbs': 28.0, 'category': 'dish'},
    
    'роллы': {'calories': 200, 'protein': 7.0, 'fat': 2.0, 'carbs': 35.0, 'category': 'dish'},
    'роллы калифорния': {'calories': 220, 'protein': 8.0, 'fat': 3.0, 'carbs': 38.0, 'category': 'dish'},
    'роллы филадельфия': {'calories': 250, 'protein': 9.0, 'fat': 5.0, 'carbs': 38.0, 'category': 'dish'},
    'роллы дракон': {'calories': 280, 'protein': 8.0, 'fat': 6.0, 'carbs': 42.0, 'category': 'dish'},
    'роллы с лососем': {'calories': 220, 'protein': 8.0, 'fat': 3.0, 'carbs': 36.0, 'category': 'dish'},
    'роллы с тунцом': {'calories': 210, 'protein': 8.0, 'fat': 2.0, 'carbs': 36.0, 'category': 'dish'},
    'роллы с угрем': {'calories': 250, 'protein': 8.0, 'fat': 5.0, 'carbs': 38.0, 'category': 'dish'},
    'роллы с креветкой': {'calories': 200, 'protein': 7.0, 'fat': 2.0, 'carbs': 35.0, 'category': 'dish'},
    'роллы темпура': {'calories': 300, 'protein': 8.0, 'fat': 10.0, 'carbs': 40.0, 'category': 'dish'},
    'роллы с авокадо': {'calories': 180, 'protein': 5.0, 'fat': 2.0, 'carbs': 35.0, 'category': 'dish'},
    'роллы с огурцом': {'calories': 160, 'protein': 5.0, 'fat': 1.0, 'carbs': 32.0, 'category': 'dish'},
    
    'нигири': {'calories': 140, 'protein': 6.0, 'fat': 1.0, 'carbs': 26.0, 'category': 'dish'},
    'нигири лосось': {'calories': 150, 'protein': 7.0, 'fat': 2.0, 'carbs': 26.0, 'category': 'dish'},
    'нигири тунец': {'calories': 140, 'protein': 7.0, 'fat': 1.0, 'carbs': 26.0, 'category': 'dish'},
    
    'сашими': {'calories': 120, 'protein': 8.0, 'fat': 1.0, 'carbs': 0.0, 'category': 'dish'},
    'сашими лосось': {'calories': 130, 'protein': 9.0, 'fat': 2.0, 'carbs': 0.0, 'category': 'dish'},
    'сашими тунец': {'calories': 120, 'protein': 9.0, 'fat': 1.0, 'carbs': 0.0, 'category': 'dish'},
    
    'гунканы': {'calories': 180, 'protein': 6.0, 'fat': 2.0, 'carbs': 32.0, 'category': 'dish'},
    
    # === ШОКОЛАД И ДЕСЕРТЫ ===
    'шоколад': {'calories': 550, 'protein': 6.0, 'fat': 35.0, 'carbs': 50.0, 'category': 'dish'},
    'шоколад молочный': {'calories': 550, 'protein': 6.0, 'fat': 35.0, 'carbs': 50.0, 'category': 'dish'},
    'шоколад горький': {'calories': 580, 'protein': 8.0, 'fat': 40.0, 'carbs': 30.0, 'category': 'dish'},
    'шоколад белый': {'calories': 560, 'protein': 5.0, 'fat': 32.0, 'carbs': 55.0, 'category': 'dish'},
    'торт': {'calories': 400, 'protein': 5.0, 'fat': 20.0, 'carbs': 50.0, 'category': 'dish'},
    'мороженое': {'calories': 200, 'protein': 4.0, 'fat': 10.0, 'carbs': 25.0, 'category': 'dish'},
    'пирожное': {'calories': 350, 'protein': 4.0, 'fat': 18.0, 'carbs': 42.0, 'category': 'dish'},
    'маффин': {'calories': 300, 'protein': 5.0, 'fat': 12.0, 'carbs': 40.0, 'category': 'dish'},
    'капкейк': {'calories': 300, 'protein': 4.0, 'fat': 14.0, 'carbs': 40.0, 'category': 'dish'},
    'пончик': {'calories': 350, 'protein': 5.0, 'fat': 18.0, 'carbs': 42.0, 'category': 'dish'},
    'круассан': {'calories': 350, 'protein': 7.0, 'fat': 20.0, 'carbs': 35.0, 'category': 'dish'},
}

# --- ДАННЫЕ О НАПИТКАХ ---
DRINK_DATA = {
    'кофе': {'base_calories': 2, 'options': {'молоко': {'add': 15}, 'сахар': {'add': 20}}, 'synonyms': ['черный кофе', 'кофе черный', 'американо', 'эспрессо']},
    'кофе с молоком': {'base_calories': 15, 'options': {'сахар': {'add': 20}}, 'synonyms': ['латте', 'капучино']},
    'какао': {'base_calories': 40, 'options': {'молоко': {'add': 15}, 'сахар': {'add': 20}}, 'synonyms': ['какао с молоком']},
    'чай': {'base_calories': 2, 'options': {'молоко': {'add': 15}, 'сахар': {'add': 20}}, 'synonyms': ['черный чай', 'чай черный', 'зеленый чай', 'чай зеленый']},
    'чай с молоком': {'base_calories': 15, 'options': {'сахар': {'add': 20}}, 'synonyms': ['чай с молоком']},
}

# --- СЛОВАРЬ ПЕРЕВОДА ---
TRANSLATE_TO_EN = {
    'вода': 'water', 'вино': 'wine', 'кола': 'coca cola', 'сок': 'juice',
    'чай': 'tea', 'кофе': 'coffee', 'молоко': 'milk', 'кефир': 'kefir',
    'йогурт': 'yogurt', 'компот': 'compote', 'лимонад': 'lemonade',
    'квас': 'kvass', 'пиво': 'beer', 'шампанское': 'champagne',
    'коньяк': 'cognac', 'водка': 'vodka', 'виски': 'whiskey',
    'торт': 'cake', 'шоколад': 'chocolate', 'мороженое': 'ice cream',
    'яблоко': 'apple', 'груша': 'pear', 'апельсин': 'orange',
    'манго': 'mango', 'киви': 'kiwi', 'виноград': 'grape',
    'клубника': 'strawberry', 'малина': 'raspberry', 'вишня': 'cherry',
    'персик': 'peach', 'абрикос': 'apricot', 'слива': 'plum',
    'лимон': 'lemon', 'лайм': 'lime', 'грейпфрут': 'grapefruit',
    'гранат': 'pomegranate', 'хурма': 'persimmon', 'инжир': 'fig',
    'финик': 'date', 'изюм': 'raisin', 'чернослив': 'prune',
    'курага': 'dried apricot', 'ананас': 'pineapple', 'арбуз': 'watermelon',
    'дыня': 'melon',
    'картошка': 'potato', 'картофель': 'potato', 'морковь': 'carrot',
    'капуста': 'cabbage', 'помидор': 'tomato', 'огурец': 'cucumber',
    'лук': 'onion', 'чеснок': 'garlic', 'свекла': 'beetroot',
    'редис': 'radish', 'репа': 'turnip', 'брокколи': 'broccoli',
    'цветная капуста': 'cauliflower', 'кабачок': 'zucchini',
    'баклажан': 'eggplant', 'перец': 'pepper',
    'курица': 'chicken', 'говядина': 'beef', 'свинина': 'pork',
    'баранина': 'lamb', 'индейка': 'turkey', 'утка': 'duck',
    'рыба': 'fish', 'лосось': 'salmon', 'семга': 'salmon',
    'форель': 'trout', 'тунец': 'tuna', 'треска': 'cod',
    'скумбрия': 'mackerel',
    'гречка': 'buckwheat', 'рис': 'rice', 'овсянка': 'oatmeal',
    'пшено': 'millet', 'перловка': 'pearl barley', 'ячневая': 'barley',
    'кукурузная': 'cornmeal', 'манная': 'semolina', 'булгур': 'bulgur',
    'кускус': 'couscous', 'полба': 'spelt', 'чечевица': 'lentils',
    'нут': 'chickpeas', 'фасоль': 'beans', 'горох': 'peas',
    'молоко': 'milk', 'кефир': 'kefir', 'йогурт': 'yogurt',
    'ряженка': 'ryazhenka', 'сыр': 'cheese', 'творог': 'cottage cheese',
    'сметана': 'sour cream', 'масло': 'butter',
    'хлеб': 'bread', 'батон': 'baguette', 'булка': 'bun', 'багет': 'baguette',
    'лаваш': 'lavash', 'лепешка': 'flatbread',
    'миндаль': 'almonds', 'грецкий орех': 'walnuts', 'кешью': 'cashews',
    'фисташки': 'pistachios', 'фундук': 'hazelnuts', 'арахис': 'peanuts',
    'авокадо': 'avocado', 'тофу': 'tofu', 'киноа': 'quinoa',
}

# --- КОЭФФИЦИЕНТЫ ПРИГОТОВЛЕНИЯ ---
COOKING_FACTORS = {
    'grain': {'boiled': {'factor': 2.5, 'oil_add': 0}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
    'vegetable': {'boiled': {'factor': 1.5, 'oil_add': 0}, 'fried': {'factor': 0.8, 'oil_add': 40}, 'deep_fried': {'factor': 0.7, 'oil_add': 80}, 'baked': {'factor': 0.8, 'oil_add': 20}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
    'fruit': {'boiled': {'factor': 1.2, 'oil_add': 0}, 'baked': {'factor': 0.8, 'oil_add': 20}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
    'egg': {'boiled': {'factor': 1.0, 'oil_add': 0}, 'fried': {'factor': 1.0, 'oil_add': 40}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
    'dairy': {'boiled': {'factor': 1.0, 'oil_add': 0}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
    'dish': {'boiled': {'factor': 1.0, 'oil_add': 0}, 'fried': {'factor': 1.0, 'oil_add': 40}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
    'drink': {'boiled': {'factor': 1.0, 'oil_add': 0}, 'steamed': {'factor': 1.0, 'oil_add': 0}},
}

DEFAULT_COOKING_FACTORS = {
    'raw': {'factor': 1.0, 'oil_add': 0},
    'boiled': {'factor': 1.0, 'oil_add': 0},
    'fried': {'factor': 1.0, 'oil_add': 40},
    'deep_fried': {'factor': 1.0, 'oil_add': 80},
    'baked': {'factor': 1.0, 'oil_add': 20},
    'steamed': {'factor': 1.0, 'oil_add': 0},
}

METHOD_DISPLAY = {
    'raw': '🥩 Сырой', 'boiled': '🍲 Вареный', 'fried': '🍳 Жареный',
    'deep_fried': '🍟 Фритюр', 'baked': '🔥 Запеченный', 'steamed': '💨 На пару',
}

GOAL_FACTORS = {'lose': 0.8, 'maintain': 1.0, 'gain': 1.2}
GOAL_DISPLAY = {
    'lose': '🏃 Сбросить вес (-20%)',
    'maintain': '⚖️ Поддерживать вес',
    'gain': '💪 Набрать массу (+20%)',
}

AVG_WEIGHT = {
    'авокадо': 150, 'банан': 120, 'яблоко': 150, 'груша': 150,
    'апельсин': 150, 'манго': 200, 'киви': 75, 'виноград': 100,
    'клубника': 15, 'малина': 5, 'вишня': 5, 'персик': 150,
    'абрикос': 50, 'слива': 50, 'лимон': 100, 'лайм': 50,
    'грейпфрут': 200, 'гранат': 200, 'хурма': 150, 'инжир': 50,
    'финик': 10, 'помидор': 100, 'огурец': 100, 'морковь': 75,
    'свекла': 150, 'редис': 20, 'репа': 150, 'кабачок': 200,
    'баклажан': 150, 'перец': 100, 'лук': 100, 'чеснок': 5,
    'брокколи': 150, 'цветная капуста': 150, 'капуста': 200,
    'шпинат': 50, 'салат листовой': 50, 'руккола': 30,
    'яйцо': 50, 'яйца': 50,
}

def convert_weight_if_needed(product_key, product_name, weight, context):
    product_lower = product_name.lower()
    if 'шт' in product_lower or 'штук' in product_lower:
        clean_name = product_lower.replace('шт', '').replace('штук', '').strip()
        for key in PRODUCTS_DB:
            if key in clean_name:
                avg_weight = AVG_WEIGHT.get(key, 100)
                new_weight = weight * avg_weight
                context.user_data['unit_info'] = f"{int(weight)} шт (~{new_weight:.0f} г)"
                context.user_data['weight'] = new_weight
                return new_weight, True
    return weight, False

def detect_drink_and_options(text):
    text_lower = text.lower()
    for drink_name, drink_data in DRINK_DATA.items():
        if drink_name in text_lower:
            return {'name': drink_name, 'base_calories': drink_data['base_calories'], 'options': drink_data['options']}
    for drink_name, drink_data in DRINK_DATA.items():
        for synonym in drink_data.get('synonyms', []):
            if synonym in text_lower:
                return {'name': drink_name, 'base_calories': drink_data['base_calories'], 'options': drink_data['options']}
    drink_keywords = ['кофе', 'чай', 'какао', 'латте', 'капучино', 'матча', 'шоколад']
    for keyword in drink_keywords:
        if keyword in text_lower:
            for drink_name, drink_data in DRINK_DATA.items():
                if keyword in drink_name.lower():
                    return {'name': drink_name, 'base_calories': drink_data['base_calories'], 'options': drink_data['options']}
    return None

def calculate_drink_calories(drink_info, weight, milk_choice=None, sugar_choice=None):
    base_calories = drink_info['base_calories']
    total = base_calories * (weight / 100)
    if milk_choice == 'with':
        total += drink_info['options'].get('молоко', {}).get('add', 15) * (weight / 100)
    if sugar_choice == 'with':
        total += drink_info['options'].get('сахар', {}).get('add', 20)
    return total

def search_product_edamam(query):
    if not EDAMAM_APP_ID or not EDAMAM_APP_KEY:
        return None
    try:
        eng_query = query
        for ru, en in TRANSLATE_TO_EN.items():
            if ru in query.lower():
                eng_query = query.lower().replace(ru, en)
                break
        if eng_query == query:
            eng_query = query
        parts = eng_query.strip().split()
        product_name = ' '.join(parts[:-1]) if len(parts) > 1 else eng_query
        weight_str = parts[-1] if len(parts) > 1 else None
        has_unit = False
        for unit in ['g', 'ml', 'l', 'кг', 'шт', 'штук', 'medium', 'large', 'small', 'cup', 'tbsp', 'tsp']:
            if unit in eng_query.lower():
                has_unit = True
                break
        if weight_str and weight_str.replace('.', '').isdigit() and not has_unit:
            weight = float(weight_str)
            if weight >= 1000:
                eng_query = f"{product_name} {weight/1000:.1f} l"
            else:
                eng_query = f"{product_name} {int(weight)} g"
        elif not has_unit and not weight_str:
            eng_query = f"{eng_query} 100g"
        url = "https://api.edamam.com/api/nutrition-data"
        params = {'app_id': EDAMAM_APP_ID, 'app_key': EDAMAM_APP_KEY, 'nutrition-type': 'logging', 'ingr': eng_query}
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            totalNutrients = data.get('totalNutrients', {})
            if totalNutrients:
                return {
                    'name': query,
                    'calories': data.get('calories', 0),
                    'protein': totalNutrients.get('PROCNT', {}).get('quantity', 0),
                    'fat': totalNutrients.get('FAT', {}).get('quantity', 0),
                    'carbs': totalNutrients.get('CHOCDF', {}).get('quantity', 0),
                }
    except Exception as e:
        logging.error(f"Edamam search error: {e}")
    return None

def save_product_to_db(name, calories, protein, fat, carbs, source='edamam'):
    try:
        existing = session.query(Product).filter_by(name=name).first()
        if existing:
            return existing
        product = Product(name=name, calories=float(calories), protein=float(protein), fat=float(fat), carbs=float(carbs), source=source)
        session.add(product)
        session.commit()
        return product
    except Exception as e:
        session.rollback()
        logging.error(f"Error saving product: {e}")
        return None

def find_product_in_db(product_name, context):
    if not product_name:
        return None, None, None
    product_lower = product_name.strip().lower()
    if product_lower in PRODUCTS_DB:
        return product_lower, PRODUCTS_DB[product_lower], 'static'
    for key in PRODUCTS_DB:
        if key in product_lower:
            product_data = PRODUCTS_DB[key]
            weight = context.user_data.get('weight', 0)
            new_weight, converted = convert_weight_if_needed(key, product_name, weight, context)
            if converted:
                return key, product_data, 'static'
            return key, product_data, 'static'
    db_product = session.query(Product).filter(Product.name.ilike(f'%{product_name}%')).first()
    if db_product:
        return db_product.name, {'calories': db_product.calories, 'protein': db_product.protein, 'fat': db_product.fat, 'carbs': db_product.carbs, 'category': None}, 'db'
    ed_data = search_product_edamam(product_name)
    if ed_data:
        saved = save_product_to_db(ed_data['name'], ed_data['calories'], ed_data['protein'], ed_data['fat'], ed_data['carbs'])
        if saved:
            return saved.name, {'calories': saved.calories, 'protein': saved.protein, 'fat': saved.fat, 'carbs': saved.carbs, 'category': None}, 'edamam'
    return None, None, None

def get_cooking_factor(product_data, method):
    category = product_data.get('category', None)
    if category == 'meat' and method == 'boiled':
        return {'factor': product_data.get('boiled_factor', 0.7), 'oil_add': 0}
    if category and category in COOKING_FACTORS and method in COOKING_FACTORS[category]:
        return COOKING_FACTORS[category][method]
    return DEFAULT_COOKING_FACTORS.get(method, {'factor': 1.0, 'oil_add': 0})

def calculate_calories_and_bju(product_name, weight, cooking_method, product_data):
    base_calories = product_data['calories']
    base_protein = product_data.get('protein', 0)
    base_fat = product_data.get('fat', 0)
    base_carbs = product_data.get('carbs', 0)
    cooking_info = get_cooking_factor(product_data, cooking_method)
    factor = cooking_info['factor']
    oil_add = cooking_info['oil_add']
    raw_weight = weight / factor if factor != 0 else weight
    total_calories = (base_calories * raw_weight / 100) + (oil_add * weight / 100)
    total_protein = base_protein * raw_weight / 100
    total_fat = base_fat * raw_weight / 100 + (oil_add * weight / 100) / 9 if oil_add > 0 else 0
    total_carbs = base_carbs * raw_weight / 100
    return total_calories, total_protein, total_fat, total_carbs, base_calories

# ===================== ИСТОРИЯ ПРИЁМОВ =====================
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        await context.bot.send_message(chat_id=chat_id, text="Сначала заполни профиль /profile")
        return

    all_meals = session.query(Meal).filter_by(user_id=user_id).order_by(Meal.meal_time.desc()).all()

    if not all_meals:
        await context.bot.send_message(chat_id=chat_id, text="📭 У тебя пока нет записей о приёмах пищи!")
        return

    days_data = {}
    for meal in all_meals:
        day_key = meal.meal_time.strftime("%Y-%m-%d")
        if day_key not in days_data:
            days_data[day_key] = []
        days_data[day_key].append(meal)

    sorted_days = sorted(days_data.keys())
    day_buttons = []
    for day_key in sorted_days:
        meals = days_data[day_key]
        total_cal = sum(m.calories for m in meals)
        day_date = datetime.strptime(day_key, "%Y-%m-%d").date()
        weekday = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"][day_date.weekday()]
        day_buttons.append(
            [InlineKeyboardButton(
                f"📅 {day_key} ({weekday}) — {round(total_cal, 1)} ккал",
                callback_data=f'history_day_{day_key}'
            )]
        )

    day_buttons.append([InlineKeyboardButton("🔙 Назад в меню", callback_data='menu_help')])
    reply_markup = InlineKeyboardMarkup(day_buttons)

    await context.bot.send_message(
        chat_id=chat_id,
        text="📜 **История приёмов пищи**\n\nВыбери день, чтобы посмотреть детали:",
        reply_markup=reply_markup
    )

async def history_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    day_key = query.data.replace('history_day_', '')

    meals = session.query(Meal).filter_by(user_id=user_id).filter(
        Meal.meal_time >= datetime.strptime(day_key, "%Y-%m-%d"),
        Meal.meal_time < datetime.strptime(day_key, "%Y-%m-%d") + timedelta(days=1)
    ).order_by(Meal.meal_time.asc()).all()

    if not meals:
        await query.edit_message_text(f"📭 За {day_key} нет записей.")
        return

    day_date = datetime.strptime(day_key, "%Y-%m-%d").date()
    weekday = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][day_date.weekday()]

    response = f"📅 **{day_key} ({weekday})**\n\n"
    total_cal = 0
    total_prot = 0
    total_fat = 0
    total_carbs = 0

    for meal in meals:
        time_str = meal.meal_time.strftime("%H:%M")
        response += f"🕐 {time_str} — {meal.product_name} {meal.weight}г — {round(meal.calories, 1)} ккал\n"
        total_cal += meal.calories
        total_prot += meal.protein
        total_fat += meal.fat
        total_carbs += meal.carbs

    response += f"\n🔥 **Всего за день: {round(total_cal, 1)} ккал**"
    response += f"\n🥩 Белки: {round(total_prot, 1)}г"
    response += f"\n🧈 Жиры: {round(total_fat, 1)}г"
    response += f"\n🍞 Углеводы: {round(total_carbs, 1)}г"

    keyboard = [[InlineKeyboardButton("🔙 Назад к истории", callback_data='menu_history')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(response, reply_markup=reply_markup)

# ===================== ВЕС И ПРОГРЕСС =====================
async def weight_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        await context.bot.send_message(chat_id=chat_id, text="Сначала заполни профиль /profile")
        return

    keyboard = [
        [InlineKeyboardButton("⚖️ Записать текущий вес", callback_data='weight_add')],
        [InlineKeyboardButton("📊 Прогресс за неделю", callback_data='weight_week')],
        [InlineKeyboardButton("📈 Прогресс за 3 недели", callback_data='weight_3weeks')],
        [InlineKeyboardButton("📉 Вся история веса", callback_data='weight_history')],
        [InlineKeyboardButton("🔙 Назад", callback_data='menu_help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    last_weight = session.query(WeightEntry).filter_by(user_id=user_id).order_by(WeightEntry.created_at.desc()).first()
    if last_weight:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚖️ **Твой текущий вес:** {last_weight.weight:.3f} кг\n"
                 f"📅 Записано: {last_weight.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                 f"Выбери действие:",
            reply_markup=reply_markup
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚖️ У тебя пока нет записей о весе.\nНажми «Записать текущий вес», чтобы начать отслеживание.\n\nВыбери действие:",
            reply_markup=reply_markup
        )

async def weight_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    await query.edit_message_text(
        "⚖️ Введи свой текущий вес в килограммах.\n"
        "📌 Можно указывать граммы через точку:\n"
        "`58.5` — 58 кг 500 г\n"
        "`58.050` — 58 кг 50 г\n"
        "`58` — 58 кг\n\n"
        "Пример: `58.5`"
    )
    context.user_data['step'] = 'weight_input'

async def handle_weight_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        weight = float(update.message.text.replace(',', '.'))

        if weight < 20 or weight > 300:
            await context.bot.send_message(chat_id=chat_id, text="❌ Вес должен быть от 20 до 300 кг. Попробуй снова:")
            return

        weight_entry = WeightEntry(user_id=user_id, weight=weight)
        session.add(weight_entry)
        session.commit()

        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user:
            old_weight = user.weight
            user.weight = weight
            if user.sex == 'М':
                bmr = 10 * weight + 6.25 * user.height - 5 * user.age + 5
            else:
                bmr = 10 * weight + 6.25 * user.height - 5 * user.age - 161
            
            activity_coeff = float(user.activity_level) if user.activity_level else 1.55
            tdee = bmr * activity_coeff
            goal_factor = GOAL_FACTORS.get(user.goal, 1.0)
            daily_calories = int(tdee * goal_factor)
            user.daily_calories = daily_calories
            user.daily_protein = round(weight * 1.8, 1)
            user.daily_fat = round(weight * 0.9, 1)
            user.daily_carbs = round((daily_calories - (user.daily_protein * 4 + user.daily_fat * 9)) / 4, 1)
            session.commit()

            three_weeks_ago = datetime.now() - timedelta(days=21)
            old_entries = session.query(WeightEntry).filter(
                WeightEntry.user_id == user_id,
                WeightEntry.created_at >= three_weeks_ago,
                WeightEntry.created_at < datetime.now() - timedelta(days=14)
            ).order_by(WeightEntry.created_at.asc()).first()

            response = f"✅ Вес **{weight:.3f} кг** сохранён!\n"
            response += f"📅 Запись от {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            
            if old_entries:
                diff = weight - old_entries.weight
                if diff < 0:
                    response += f"🎉 За 3 недели ты сбросил **{abs(diff):.3f} кг**! (с {old_entries.weight:.3f} до {weight:.3f}) 📉\n"
                elif diff > 0:
                    response += f"📈 За 3 недели ты набрал **{diff:.3f} кг** (с {old_entries.weight:.3f} до {weight:.3f})\n"
                else:
                    response += f"⚖️ Вес за 3 недели не изменился (было {old_entries.weight:.3f} кг)\n"
            else:
                response += "📊 Пока нет данных для сравнения за 3 недели.\n"

            response += f"\n🔥 Норма калорий обновлена: **{daily_calories} ккал**"
            await context.bot.send_message(chat_id=chat_id, text=response)
        else:
            await context.bot.send_message(chat_id=chat_id, text="✅ Вес сохранён!")

        context.user_data['step'] = None

    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка! Введи число. Например: `58.5`")
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка: {e}")
        logging.error(f"Weight input error: {e}")

async def weight_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    week_ago = datetime.now() - timedelta(days=7)
    entries = session.query(WeightEntry).filter(
        WeightEntry.user_id == user_id,
        WeightEntry.created_at >= week_ago
    ).order_by(WeightEntry.created_at.asc()).all()

    if len(entries) < 2:
        await query.edit_message_text("📊 Недостаточно данных для анализа за неделю. Запиши свой вес минимум 2 раза с интервалом в неделю.")
        return

    first = entries[0]
    last = entries[-1]
    diff = last.weight - first.weight

    response = f"📊 **Прогресс за неделю**\n\n"
    response += f"📅 {first.created_at.strftime('%d.%m.%Y')}: **{first.weight:.3f} кг**\n"
    response += f"📅 {last.created_at.strftime('%d.%m.%Y')}: **{last.weight:.3f} кг**\n\n"

    if diff < 0:
        response += f"🎉 Ты сбросил **{abs(diff):.3f} кг**! 📉\n"
        response += f"📉 Средняя скорость: **{abs(diff)/7:.3f} кг/день**"
    elif diff > 0:
        response += f"📈 Ты набрал **{diff:.3f} кг**\n"
        response += f"📈 Средняя скорость: **{diff/7:.3f} кг/день**"
    else:
        response += "⚖️ Вес не изменился за неделю."

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='menu_weight')]]
    await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))

async def weight_3weeks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    three_weeks_ago = datetime.now() - timedelta(days=21)
    entries = session.query(WeightEntry).filter(
        WeightEntry.user_id == user_id,
        WeightEntry.created_at >= three_weeks_ago
    ).order_by(WeightEntry.created_at.asc()).all()

    if len(entries) < 2:
        await query.edit_message_text("📊 Недостаточно данных для анализа за 3 недели. Нужно минимум 2 записи с интервалом в 3 недели.")
        return

    first = entries[0]
    last = entries[-1]
    diff = last.weight - first.weight

    response = f"📈 **Прогресс за 3 недели**\n\n"
    response += f"📅 {first.created_at.strftime('%d.%m.%Y')}: **{first.weight:.3f} кг**\n"
    response += f"📅 {last.created_at.strftime('%d.%m.%Y')}: **{last.weight:.3f} кг**\n\n"

    if diff < 0:
        response += f"🎉 Ты сбросил **{abs(diff):.3f} кг**! 📉\n"
        response += f"📉 Средняя скорость: **{abs(diff)/21:.3f} кг/день**"
    elif diff > 0:
        response += f"📈 Ты набрал **{diff:.3f} кг**\n"
        response += f"📈 Средняя скорость: **{diff/21:.3f} кг/день**"
    else:
        response += "⚖️ Вес не изменился за 3 недели."

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='menu_weight')]]
    await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))

async def weight_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    entries = session.query(WeightEntry).filter_by(user_id=user_id).order_by(WeightEntry.created_at.desc()).all()

    if not entries:
        await query.edit_message_text("📭 У тебя пока нет записей о весе.")
        return

    response = "📉 **Вся история веса**\n\n"
    for entry in entries[:20]:
        response += f"📅 {entry.created_at.strftime('%d.%m.%Y %H:%M')}: **{entry.weight:.3f} кг**\n"

    if len(entries) > 20:
        response += f"\n... и ещё {len(entries) - 20} записей"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='menu_weight')]]
    await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))

# ===================== АВТОМАТИЧЕСКИЕ УВЕДОМЛЕНИЯ =====================
async def send_weekly_reminder(app: Application):
    users = session.query(User).all()
    for user in users:
        try:
            await app.bot.send_message(
                chat_id=user.telegram_id,
                text="📅 **Напоминание о взвешивании!**\n\nПрошла неделя — пора записать свой вес!\n⚖️ Нажми на кнопку **«Вес/Прогресс»** в главном меню,\nзатем выбери **«Записать текущий вес»**.\n\n📊 Это поможет отслеживать твой прогресс!"
            )
        except Exception as e:
            logging.error(f"Failed to send reminder to {user.telegram_id}: {e}")

async def send_3week_progress(app: Application):
    users = session.query(User).all()
    three_weeks_ago = datetime.now() - timedelta(days=21)
    two_weeks_ago = datetime.now() - timedelta(days=14)
    
    for user in users:
        try:
            old_entry = session.query(WeightEntry).filter(
                WeightEntry.user_id == user.telegram_id,
                WeightEntry.created_at >= three_weeks_ago,
                WeightEntry.created_at < two_weeks_ago
            ).order_by(WeightEntry.created_at.asc()).first()
            
            last_entry = session.query(WeightEntry).filter_by(
                user_id=user.telegram_id
            ).order_by(WeightEntry.created_at.desc()).first()
            
            if old_entry and last_entry:
                diff = last_entry.weight - old_entry.weight
                response = f"📊 **Отчёт о прогрессе за 3 недели!**\n\n"
                response += f"📅 {old_entry.created_at.strftime('%d.%m.%Y')}: **{old_entry.weight:.3f} кг**\n"
                response += f"📅 {last_entry.created_at.strftime('%d.%m.%Y')}: **{last_entry.weight:.3f} кг**\n\n"
                
                if diff < 0:
                    response += f"🎉 За 3 недели ты сбросил **{abs(diff):.3f} кг**! 📉\n"
                    response += f"🔥 Отличный результат! Продолжай в том же духе! 💪"
                elif diff > 0:
                    response += f"📈 За 3 недели ты набрал **{diff:.3f} кг**.\n"
                    if user.goal == 'lose':
                        response += "⚠️ Возможно, стоит пересмотреть питание и увеличить активность."
                    else:
                        response += "💪 Если это твоя цель — отлично, продолжай!"
                else:
                    response += "⚖️ Вес не изменился за 3 недели.\n"
                    response += "💡 Попробуй скорректировать питание или добавить тренировки."
                
                await app.bot.send_message(chat_id=user.telegram_id, text=response)
        except Exception as e:
            logging.error(f"Failed to send 3-week progress to {user.telegram_id}: {e}")

# ===================== ОСНОВНЫЕ ФУНКЦИИ БОТА =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = session.query(User).filter_by(telegram_id=user.id).first()
    chat_id = update.effective_chat.id
    
    if existing:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Привет, {existing.first_name}! 👋\n"
                 f"Твоя норма: {existing.daily_calories} ккал в день.\n"
                 f"Цель: {GOAL_DISPLAY.get(existing.goal, existing.goal)}\n\n"
                 "Я помогу тебе отслеживать КБЖУ, воду и вес.\n"
                 "Выбери действие:",
            reply_markup=main_menu_keyboard()
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Привет! 👋 Я бот для контроля КБЖУ.\n\n"
                 "Сначала давай заполним твой профиль, чтобы я мог рассчитать норму калорий и воды.\n"
                 "Напиши свои данные в формате:\n"
                 "`Пол Возраст Рост Вес`\n"
                 "Например: `М 25 180 75`\n\n"
                 "После заполнения я покажу тебе главное меню."
        )
        context.user_data['step'] = 'profile_data'

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()
    chat_id = update.effective_chat.id
    
    if user:
        activity_display = {
            '1.2': '🛋 Сидячий',
            '1.375': '🚶 Легкая',
            '1.55': '🏋️ Средняя',
            '1.725': '🏃 Высокая',
            '1.9': '🔥 Очень высокая'
        }.get(user.activity_level, user.activity_level)
        goal_display = GOAL_DISPLAY.get(user.goal, user.goal)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📊 **Твой профиль:**\n\n"
                 f"👤 Пол: {user.sex}\n"
                 f"📅 Возраст: {user.age} лет\n"
                 f"📏 Рост: {user.height} см\n"
                 f"⚖️ Вес: {user.weight} кг\n"
                 f"🏃 Активность: {activity_display}\n"
                 f"🎯 Цель: {goal_display}\n"
                 f"🔥 Норма калорий: {user.daily_calories} ккал\n"
                 f"🥩 Белки: {user.daily_protein}г\n"
                 f"🧈 Жиры: {user.daily_fat}г\n"
                 f"🍞 Углеводы: {user.daily_carbs}г\n"
                 f"💧 Вода: {round(user.weight * 30 / 1000, 1)}л в день\n\n"
                 f"✏️ Чтобы **обновить** профиль, отправь новые данные в формате:\n"
                 f"`Пол Возраст Рост Вес`\n"
                 f"Например: `Ж 18 171 58`\n\n"
                 f"⚠️ Это перезапишет текущие данные."
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="📝 У тебя пока нет профиля. Давай заполним!\n"
                 "Напиши свой пол (М/Ж), возраст, рост (в см), вес (в кг) через пробел.\n"
                 "Пример: Ж 18 171 58"
        )
        context.user_data['step'] = 'profile_data'

async def handle_profile_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        sex = parts[0].upper()
        age = int(parts[1])
        height = float(parts[2])
        weight = float(parts[3])
        
        if age < 10 or age > 120 or height < 50 or height > 250 or weight < 20 or weight > 300:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Что-то не так с данными. Проверь:\n"
                     "Возраст: 10-120 лет\nРост: 50-250 см\nВес: 20-300 кг\n"
                     "Попробуй еще раз: Ж 18 171 58"
            )
            return
        
        context.user_data['sex'] = sex
        context.user_data['age'] = age
        context.user_data['height'] = height
        context.user_data['weight'] = weight
        
        keyboard = [
            [InlineKeyboardButton("🛋 Сидячий (офис)", callback_data='1.2')],
            [InlineKeyboardButton("🚶 Легкая (1-3 раза/нед)", callback_data='1.375')],
            [InlineKeyboardButton("🏋️ Средняя (3-5 раз/нед)", callback_data='1.55')],
            [InlineKeyboardButton("🏃 Высокая (6-7 раз/нед)", callback_data='1.725')],
            [InlineKeyboardButton("🔥 Очень высокая", callback_data='1.9')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Шаг 1: Выбери уровень физической активности:",
            reply_markup=reply_markup
        )
        context.user_data['step'] = 'profile_activity'
        
    except (ValueError, IndexError):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Ошибка! Введи данные в формате: Пол Возраст Рост Вес\nПример: Ж 18 171 58"
        )
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Ошибка. Попробуй снова /profile"
        )
        logging.error(f"Profile error: {e}")

async def handle_activity_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['activity_coeff'] = float(query.data)
    
    keyboard = [
        [InlineKeyboardButton("🏃 Сбросить вес (-20%)", callback_data='lose')],
        [InlineKeyboardButton("⚖️ Поддерживать вес", callback_data='maintain')],
        [InlineKeyboardButton("💪 Набрать массу (+20%)", callback_data='gain')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Шаг 2: Выбери свою цель:",
        reply_markup=reply_markup
    )
    context.user_data['step'] = 'profile_goal'

async def handle_goal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    goal = query.data
    context.user_data['goal'] = goal
    
    sex = context.user_data.get('sex')
    age = context.user_data.get('age')
    height = context.user_data.get('height')
    weight = context.user_data.get('weight')
    activity_coeff = context.user_data.get('activity_coeff')
    
    if sex == 'М':
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    
    tdee = bmr * activity_coeff
    goal_factor = GOAL_FACTORS.get(goal, 1.0)
    daily_calories = int(tdee * goal_factor)
    
    protein = round(weight * 1.8, 1)
    fat = round(weight * 0.9, 1)
    carbs = round((daily_calories - (protein * 4 + fat * 9)) / 4, 1)
    
    telegram_id = update.effective_user.id
    existing_user = session.query(User).filter_by(telegram_id=telegram_id).first()
    
    if existing_user:
        existing_user.sex = sex
        existing_user.age = age
        existing_user.height = height
        existing_user.weight = weight
        existing_user.activity_level = str(activity_coeff)
        existing_user.goal = goal
        existing_user.daily_calories = daily_calories
        existing_user.daily_protein = protein
        existing_user.daily_fat = fat
        existing_user.daily_carbs = carbs
        session.commit()
        message = "✅ Профиль обновлен!"
    else:
        user = User(
            telegram_id=telegram_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            sex=sex,
            age=age,
            height=height,
            weight=weight,
            activity_level=str(activity_coeff),
            goal=goal,
            daily_calories=daily_calories,
            daily_protein=protein,
            daily_fat=fat,
            daily_carbs=carbs
        )
        session.add(user)
        session.commit()
        message = "✅ Профиль создан!"
    
    goal_display = GOAL_DISPLAY.get(goal, goal)
    
    weight_entry = WeightEntry(user_id=telegram_id, weight=weight)
    session.add(weight_entry)
    session.commit()
    
    await query.edit_message_text(
        f"{message}\n\n"
        f"📊 Твои данные:\n"
        f"BMR: {round(bmr, 0)} ккал\n"
        f"TDEE: {round(tdee, 0)} ккал\n"
        f"Цель: {goal_display}\n"
        f"🔥 Суточная норма: {daily_calories} ккал\n\n"
        f"🥩 Белки: {protein}г\n"
        f"🧈 Жиры: {fat}г\n"
        f"🍞 Углеводы: {carbs}г\n\n"
        f"💧 Норма воды: {round(weight * 30 / 1000, 1)}л в день\n\n"
        f"⚖️ Начальный вес **{weight:.3f} кг** сохранён!\n\n"
        f"☕ По умолчанию: кофе 100 = кофе с молоком и сахаром (35 ккал)\n"
        f"Варианты: кофе без молока, кофе без сахара, кофе черный\n\n"
        f"Теперь ты можешь добавлять приемы пищи просто написав: продукт вес\n"
        f"Воду добавляй: вода 500\n\n"
        f"Каждое воскресенье я буду напоминать взвеситься! 📅\n\n"
        f"Выбери действие:",
        reply_markup=main_menu_keyboard()
    )
    context.user_data['step'] = None

# --- Ручное добавление продукта ---
async def add_my_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📝 Введи данные о продукте в формате:\n"
             "Название Калории Белки Жиры Углеводы\n"
             "Пример: Тофу 160 8 10 2\n"
             "⚠️ Продукт будет доступен ВСЕМ пользователям!"
    )
    context.user_data['step'] = 'add_product'

async def handle_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) < 5:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Нужно 5 значений: Название, Калории, Белки, Жиры, Углеводы")
            return
        
        name = ' '.join(parts[:-4]).strip()
        calories = float(parts[-4])
        protein = float(parts[-3])
        fat = float(parts[-2])
        carbs = float(parts[-1])
        
        if calories < 0 or protein < 0 or fat < 0 or carbs < 0:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Все значения должны быть положительными!")
            return
        
        product = Product(name=name.capitalize(), calories=calories, protein=protein, fat=fat, carbs=carbs, source='user')
        session.add(product)
        session.commit()
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Продукт '{name.capitalize()}' добавлен в общую базу!\n"
                 f"🔥 {calories} ккал, 🥩 {protein}г, 🧈 {fat}г, 🍞 {carbs}г на 100г.\n"
                 f"Теперь ВСЕ пользователи могут его найти просто написав: продукт вес"
        )
        context.user_data['step'] = None
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка! Введи числа правильно.\nПример: Тофу 160 8 10 2")
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка: {e}. Попробуй снова.")
        logging.error(f"Add product error: {e}")

# --- ВОДА ---
async def add_water(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) < 2:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="💧 Напиши сколько воды выпил в мл или литрах\nПримеры:\nвода 500 - 500 мл\nвода 1.5 - 1.5 литра\nвода 0.5 - 0.5 литра")
            return
        
        amount_str = parts[1].replace(',', '.')
        amount = float(amount_str)
        
        if amount < 10:
            amount = amount * 1000
        
        if amount <= 0 or amount > 10000:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Объём должен быть от 1 до 10000 мл.")
            return
        
        water = Water(user_id=update.effective_user.id, amount=amount)
        session.add(water)
        session.commit()
        
        today = datetime.now().date()
        user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
        
        if user:
            water_entries = session.query(Water).filter_by(user_id=update.effective_user.id).all()
            water_today = sum(w.amount for w in water_entries if w.created_at.date() == today)
            water_norm = user.weight * 30
            
            progress = f"Выпито {round(water_today / 1000, 1)}л из {round(water_norm / 1000, 1)}л"
            if water_today >= water_norm:
                progress += " ✅ Норма выполнена!"
            else:
                progress += f" (осталось {round((water_norm - water_today) / 1000, 1)}л)"
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Добавлено {amount} мл воды!\n💧 {progress}")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Добавлено {amount} мл воды!")
        
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка! Введи число. Пример: вода 500")
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка: {e}")
        logging.error(f"Water error: {e}")

# --- ПРОСМОТР ПРИЁМОВ ПИЩИ ---
async def my_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = datetime.now().date()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    chat_id = update.effective_chat.id
    
    if not user:
        await context.bot.send_message(chat_id=chat_id, text="Сначала заполни профиль командой /profile")
        return
    
    meals = session.query(Meal).filter_by(user_id=user_id).filter(Meal.meal_time >= today).order_by(Meal.meal_time.asc()).all()
    
    if not meals:
        await context.bot.send_message(chat_id=chat_id, text="🍽 Сегодня ещё ничего не съедено!")
        return
    
    total_cal = sum(m.calories for m in meals)
    total_prot = sum(m.protein for m in meals)
    total_fat = sum(m.fat for m in meals)
    total_carbs = sum(m.carbs for m in meals)
    
    water_entries = session.query(Water).filter_by(user_id=user_id).all()
    water_today = sum(w.amount for w in water_entries if w.created_at.date() == today)
    water_norm = user.weight * 30
    
    cal_diff = user.daily_calories - total_cal
    prot_diff = user.daily_protein - total_prot
    fat_diff = user.daily_fat - total_fat
    carbs_diff = user.daily_carbs - total_carbs
    water_diff = water_norm - water_today
    
    if cal_diff > 0:
        cal_status = f"✅ Осталось {round(cal_diff, 1)} ккал"
    elif cal_diff == 0:
        cal_status = "🎯 Ты точно в норме!"
    else:
        cal_status = f"⚠️ Перебор на {round(abs(cal_diff), 1)} ккал"
    
    prot_status = f"🥩 {round(total_prot,1)} / {user.daily_protein}г (осталось {round(prot_diff,1)}г)" if prot_diff > 0 else f"🥩 {round(total_prot,1)} / {user.daily_protein}г (перебор {round(abs(prot_diff),1)}г)"
    fat_status = f"🧈 {round(total_fat,1)} / {user.daily_fat}г (осталось {round(fat_diff,1)}г)" if fat_diff > 0 else f"🧈 {round(total_fat,1)} / {user.daily_fat}г (перебор {round(abs(fat_diff),1)}г)"
    carbs_status = f"🍞 {round(total_carbs,1)} / {user.daily_carbs}г (осталось {round(carbs_diff,1)}г)" if carbs_diff > 0 else f"🍞 {round(total_carbs,1)} / {user.daily_carbs}г (перебор {round(abs(carbs_diff),1)}г)"
    water_status = f"💧 {round(water_today/1000,1)}л / {round(water_norm/1000,1)}л (осталось {round(water_diff/1000,1)}л)" if water_diff > 0 else f"💧 {round(water_today/1000,1)}л / {round(water_norm/1000,1)}л ✅ Норма выполнена!"
    
    response = "📋 Твои приёмы пищи за сегодня:\n\n"
    for i, meal in enumerate(meals, 1):
        time_str = meal.meal_time.strftime("%H:%M")
        response += f"{i}. {time_str} — {meal.product_name} {meal.weight}г — {round(meal.calories, 1)} ккал\n"
    
    response += f"\n🔥 Всего: {round(total_cal, 1)} ккал"
    response += f"\n{cal_status}"
    response += f"\n{prot_status}"
    response += f"\n{fat_status}"
    response += f"\n{carbs_status}"
    response += f"\n{water_status}"
    
    keyboard = [[InlineKeyboardButton("🗑 Удалить последний приём", callback_data='delete_last_meal')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(chat_id=chat_id, text=response, reply_markup=reply_markup)

# --- УДАЛЕНИЕ ПОСЛЕДНЕГО ПРИЁМА ---
async def delete_last_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    today = datetime.now().date()
    chat_id = update.effective_chat.id
    
    try:
        last_meal = session.query(Meal).filter_by(user_id=user_id).filter(Meal.meal_time >= today).order_by(Meal.meal_time.desc()).first()
        
        if not last_meal:
            await query.edit_message_text("❌ Нет записей для удаления!")
            return
        
        product_name = last_meal.product_name
        weight = last_meal.weight
        calories = round(last_meal.calories, 1)
        
        session.delete(last_meal)
        session.commit()
        
        meals = session.query(Meal).filter_by(user_id=user_id).filter(Meal.meal_time >= today).order_by(Meal.meal_time.asc()).all()
        
        if not meals:
            await query.edit_message_text(f"🗑 Удалено!\nПродукт: {product_name} ({weight}г) — {calories} ккал\n\n🍽 Сегодня больше ничего не съедено!")
            return
        
        response = "📋 Обновлённый список:\n\n"
        total_cal = 0
        for i, meal in enumerate(meals, 1):
            time_str = meal.meal_time.strftime("%H:%M")
            response += f"{i}. {time_str} — {meal.product_name} {meal.weight}г — {round(meal.calories, 1)} ккал\n"
            total_cal += meal.calories
        
        response += f"\n🔥 Всего: {round(total_cal, 1)} ккал"
        
        keyboard = [[InlineKeyboardButton("🗑 Удалить последний приём", callback_data='delete_last_meal')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🗑 Удалено!\nПродукт: {product_name} ({weight}г) — {calories} ккал\n\n{response}",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logging.error(f"Delete meal error: {e}")
        await query.edit_message_text(f"❌ Ошибка при удалении: {e}")

# --- ПЛАН НА ЗАВТРА ---
async def check_overeating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()
    chat_id = update.effective_chat.id

    if not user:
        await context.bot.send_message(chat_id=chat_id, text="Сначала заполни профиль /profile", reply_markup=main_menu_keyboard())
        return

    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)

    two_days_ago = now - timedelta(days=2)
    meals = session.query(Meal).filter_by(user_id=user_id).filter(Meal.meal_time >= two_days_ago).all()

    if not meals:
        await context.bot.send_message(chat_id=chat_id, text="📊 Нет данных за последние 2 дня для анализа.\n\nДобавь приёмы пищи, чтобы я мог составить план!", reply_markup=main_menu_keyboard())
        return

    days_data = {}
    for meal in meals:
        day = meal.meal_time.date()
        days_data[day] = days_data.get(day, 0) + meal.calories

    overeat_days = []
    for day in [yesterday, day_before_yesterday]:
        if day in days_data and days_data[day] > user.daily_calories:
            overeat_days.append(days_data[day] - user.daily_calories)

    if len(overeat_days) >= 2:
        avg_overeat = sum(overeat_days) / len(overeat_days)

        last_plan = session.query(DailyPlan).filter_by(user_id=user_id).order_by(DailyPlan.created_at.desc()).first()
        if last_plan and last_plan.created_at.date() == yesterday:
            extra_deficit = int(avg_overeat * 0.1)
            avg_overeat += extra_deficit

        target_calories = int(user.daily_calories - avg_overeat)
        min_cal = int(user.daily_calories * 0.5)
        max_cal = int(user.daily_calories * 0.9)
        target_calories = max(min_cal, min(target_calories, max_cal))

        meals_base = [
            {"name": "Завтрак", "products": "Овсянка 40г на воде + Яблоко 150г", "calories": 200},
            {"name": "Обед", "products": "Курица паровая 150г + Гречка 80г", "calories": 350},
            {"name": "Ужин", "products": "Рыба 150г + Овощи 200г", "calories": 300},
            {"name": "Перекус", "products": "Творог 100г", "calories": 120},
        ]

        base_total = sum(m["calories"] for m in meals_base)
        if target_calories < base_total:
            ratio = target_calories / base_total
            for m in meals_base:
                m["calories"] = int(m["calories"] * ratio)
        elif target_calories > base_total:
            extra = target_calories - base_total
            meals_base.append({"name": "Дополнительный перекус", "products": f"Орехи/фрукты (~{extra} ккал)", "calories": extra})

        total_plan = sum(m["calories"] for m in meals_base)

        plan_json = json.dumps(meals_base, ensure_ascii=False)
        new_plan = DailyPlan(user_id=user_id, plan_date=now, meals=plan_json, total_calories=total_plan, target_calories=target_calories)
        session.add(new_plan)
        session.commit()

        response = f"📅 **План питания на завтра** (адаптирован под твой перебор)\n"
        response += f"🔥 Твоя норма: {user.daily_calories} ккал\n"
        response += f"📉 Средний перебор за 2 дня: {round(avg_overeat)} ккал\n"
        if last_plan and last_plan.created_at.date() == yesterday:
            response += f"⚠️ Ты уже получал план вчера — дефицит увеличен на 10% от перебора\n"
        response += f"🎯 Цель на завтра: {target_calories} ккал\n\n"

        for m in meals_base:
            response += f"🍽 **{m['name']}**: {m['products']} — {m['calories']} ккал\n"

        response += f"\n📊 Всего по плану: {total_plan} ккал"
        response += f"\n💡 Это **рекомендация**, а не строгое предписание."

        await context.bot.send_message(chat_id=chat_id, text=response, reply_markup=main_menu_keyboard())
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"✅ Ты в норме! Перееданий за последние 2 дня: {len(overeat_days)}\nПродолжай следить за питанием! 💪", reply_markup=main_menu_keyboard())

# --- ОСНОВНЫЕ ФУНКЦИИ ---
async def add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🍽 Напиши, что ты съел, в формате:\nПродукт вес (например: Гречка 100)\nЯ спрошу способ приготовления.")
    context.user_data['step'] = 'meal'

async def handle_meal_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) < 2:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Напиши продукт и вес через пробел. Например: Гречка 100")
            return
        
        product_name = ' '.join(parts[:-1])
        weight = float(parts[-1])
        
        if weight <= 0 or weight > 5000:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Вес должен быть от 1 до 5000 грамм.")
            return
        
        context.user_data['product_name'] = product_name.lower()
        context.user_data['weight'] = weight
        context.user_data['original_weight'] = weight
        
        keyboard = [
            [InlineKeyboardButton("🥩 Сырой", callback_data='raw')],
            [InlineKeyboardButton("🍲 Вареный", callback_data='boiled')],
            [InlineKeyboardButton("🍳 Жареный", callback_data='fried')],
            [InlineKeyboardButton("🍟 Фритюр", callback_data='deep_fried')],
            [InlineKeyboardButton("🔥 Запеченный", callback_data='baked')],
            [InlineKeyboardButton("💨 На пару", callback_data='steamed')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Выбери способ приготовления для {product_name}:", reply_markup=reply_markup)
        context.user_data['step'] = 'cooking_method'
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка! Вес должен быть числом. Например: Гречка 100")
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка: {e}")
        logging.error(f"Meal error: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query is not None:
        return
    if update.message and update.message.text and update.message.text.startswith('/'):
        return
    
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if context.user_data.get('step') == 'weight_input':
        await handle_weight_input(update, context)
        return
    
    if text.lower().startswith('вода'):
        await add_water(update, context)
        return
    
    parts = text.split()
    if len(parts) >= 2:
        try:
            product_name = ' '.join(parts[:-1])
            amount = float(parts[-1])
            
            if amount <= 0 or amount > 5000:
                await context.bot.send_message(chat_id=chat_id, text="❌ Количество должно быть от 1 до 5000 (грамм или мл).")
                return
            
            found_key, product_data, source = find_product_in_db(product_name, context)
            if product_data:
                context.user_data['product_name'] = product_name
                context.user_data['weight'] = amount
                
                is_drink = product_data.get('category') == 'drink'
                unit_display = "мл" if is_drink else "г"
                
                if is_drink:
                    calories = product_data['calories'] * (amount / 100)
                    protein = product_data.get('protein', 0) * (amount / 100)
                    fat = product_data.get('fat', 0) * (amount / 100)
                    carbs = product_data.get('carbs', 0) * (amount / 100)
                    
                    meal = Meal(
                        user_id=update.effective_user.id,
                        product_name=found_key,
                        weight=amount,
                        cooking_method='raw',
                        calories=calories,
                        protein=protein,
                        fat=fat,
                        carbs=carbs
                    )
                    session.add(meal)
                    session.commit()
                    
                    hint = ""
                    if found_key == 'кофе':
                        hint = "\n\n☕ По умолчанию: кофе с молоком и сахаром (35 ккал)\nБез молока: 'кофе без молока'\nБез сахара: 'кофе без сахара'\nЧёрный: 'кофе черный'"
                    elif found_key == 'чай':
                        hint = "\n\n🍵 По умолчанию: чёрный чай\nС молоком: 'чай с молоком'\nС сахаром: 'чай с сахаром'"
                    elif found_key in ['пиво', 'водка', 'вино', 'коньяк', 'виски', 'ром', 'джин', 'текила', 'ликер', 'мартини', 'шампанское']:
                        hint = f"\n\n🍷 {found_key.capitalize()} — {amount} мл"
                    
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ Добавлено!\nПродукт: {found_key}\nОбъём: {amount} {unit_display}\n🔥 Калорийность: {round(calories, 1)} ккал\n🥩 Белки: {round(protein, 1)}г\n🧈 Жиры: {round(fat, 1)}г\n🍞 Углеводы: {round(carbs, 1)}г{hint}"
                    )
                    return
                else:
                    keyboard = [
                        [InlineKeyboardButton("🥩 Сырой", callback_data='raw')],
                        [InlineKeyboardButton("🍲 Вареный", callback_data='boiled')],
                        [InlineKeyboardButton("🍳 Жареный", callback_data='fried')],
                        [InlineKeyboardButton("🍟 Фритюр", callback_data='deep_fried')],
                        [InlineKeyboardButton("🔥 Запеченный", callback_data='baked')],
                        [InlineKeyboardButton("💨 На пару", callback_data='steamed')],
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(chat_id=chat_id, text=f"Выбери способ приготовления для {product_name} ({amount}г):", reply_markup=reply_markup)
                    context.user_data['step'] = 'cooking_method'
                    return
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Продукт '{product_name}' не найден.\nПопробуй написать по-другому:\n- На английском (avocado, tofu)\n- Или добавь вручную командой /add_my_product")
                return
        except ValueError:
            pass
    
    step = context.user_data.get('step')
    if step == 'profile_data':
        await handle_profile_input(update, context)
        return
    elif step == 'meal':
        await handle_meal_input(update, context)
        return
    elif step == 'add_product':
        await handle_add_product(update, context)
        return
    elif step == 'cooking_method':
        return
    
    await context.bot.send_message(
        chat_id=chat_id,
        text="Я не понимаю эту команду.\nПросто напиши продукт и вес (например: Гречка 100) или напиток (кофе 100)\n☕ По умолчанию: кофе 100 = с молоком и сахаром (35 ккал)\n   без молока: 'кофе без молока'\n   без сахара: 'кофе без сахара'\n   чёрный: 'кофе черный'\n🍷 Алкоголь указывай в мл: 'вино 450', 'пиво 500', 'водка 50'\nВоду добавляй: вода 500\nВес записывай через кнопку «Вес/Прогресс»\nПосмотреть свои приёмы: /my_food\nПлан на завтра: /plan\nИспользуй команды:\n/start, /profile, /add_my_product, /stats, /help"
    )

async def handle_cooking_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data
    product_name = context.user_data.get('product_name')
    weight = context.user_data.get('weight', 0)
    
    found_key, product_data, source = find_product_in_db(product_name, context)
    if not product_data:
        await query.edit_message_text("❌ Продукт не найден")
        context.user_data['step'] = None
        return
    
    total_calories, total_protein, total_fat, total_carbs, base_calories = calculate_calories_and_bju(product_name, weight, method, product_data)
    
    meal = Meal(
        user_id=update.effective_user.id,
        product_name=found_key,
        weight=weight,
        cooking_method=method,
        calories=total_calories,
        protein=total_protein,
        fat=total_fat,
        carbs=total_carbs
    )
    session.add(meal)
    session.commit()
    
    method_display = METHOD_DISPLAY.get(method, method)
    unit_info = context.user_data.get('unit_info', '')
    weight_display = f"{weight}г" if not unit_info else unit_info
    
    response = f"✅ Добавлено!\nПродукт: {found_key}\nВес: {weight_display}\nСпособ: {method_display}\nИсточник: {source}\nБаза (100г сырого): {base_calories} ккал\n🔥 Калорийность: {round(total_calories, 1)} ккал\n🥩 Белки: {round(total_protein, 1)}г\n🧈 Жиры: {round(total_fat, 1)}г\n🍞 Углеводы: {round(total_carbs, 1)}г"
    
    if method == 'fried':
        response += "\n\n💡 При жарке добавляется ~40 ккал на 100г от масла."
    elif method == 'deep_fried':
        response += "\n\n🍟 Фритюр: масла впитывается в 2 раза больше (~80 ккал на 100г)."
    
    response += "\n\nПродолжай добавлять еду просто написав: продукт вес"
    
    await query.edit_message_text(response)
    context.user_data['step'] = None

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = session.query(User).filter_by(telegram_id=user_id).first()
    chat_id = update.effective_chat.id
    
    if not user:
        await context.bot.send_message(chat_id=chat_id, text="Сначала заполни профиль командой /profile")
        return
    
    today = datetime.now().date()
    meals = session.query(Meal).filter_by(user_id=user_id).filter(Meal.meal_time >= today).all()
    
    total_calories = sum(m.calories for m in meals)
    total_protein = sum(m.protein for m in meals)
    total_fat = sum(m.fat for m in meals)
    total_carbs = sum(m.carbs for m in meals)
    
    water_entries = session.query(Water).filter_by(user_id=user_id).all()
    water_today = sum(w.amount for w in water_entries if w.created_at.date() == today)
    water_norm = user.weight * 30
    
    remaining_cal = user.daily_calories - total_calories
    remaining_protein = user.daily_protein - total_protein
    remaining_fat = user.daily_fat - total_fat
    remaining_carbs = user.daily_carbs - total_carbs
    
    if remaining_cal > 200:
        status = "✅ Ты в норме! Можно еще поесть 😊"
    elif 0 <= remaining_cal <= 200:
        status = "🎯 Почти точно! Можно остановиться."
    else:
        status = "⚠️ Перебор! Завтра постарайся меньше."
    
    if water_today >= water_norm:
        water_status = "💧 Отлично! Воды достаточно ✅"
    elif water_today >= water_norm * 0.7:
        water_status = f"💧 Хорошо, но ещё {round((water_norm - water_today) / 1000, 1)}л до нормы"
    else:
        water_status = f"💧 Мало воды! Нужно ещё {round((water_norm - water_today) / 1000, 1)}л"
    
    goal_display = GOAL_DISPLAY.get(user.goal, user.goal)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Твоя статистика за сегодня:\nЦель: {goal_display}\n\n🔥 Калории: {round(total_calories, 1)} / {user.daily_calories} ккал (осталось {round(remaining_cal, 1)})\n🥩 Белки: {round(total_protein, 1)} / {user.daily_protein}г (осталось {round(remaining_protein, 1)})\n🧈 Жиры: {round(total_fat, 1)} / {user.daily_fat}г (осталось {round(remaining_fat, 1)})\n🍞 Углеводы: {round(total_carbs, 1)} / {user.daily_carbs}г (осталось {round(remaining_carbs, 1)})\n\n💧 Вода: {round(water_today / 1000, 1)}л из {round(water_norm / 1000, 1)}л\n{water_status}\n\n{status}"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🤖 **Команды бота:**\n\n"
             "`/start` — приветствие и краткая справка\n"
             "`/profile` — посмотреть или обновить свой профиль\n"
             "`/add_my_product` — добавить свой продукт в общую базу\n"
             "`/my_food` — посмотреть приёмы за сегодня + остаток КБЖУ\n"
             "`/stats` — статистика за сегодня (калории + вода)\n"
             "`/plan` — план питания на завтра, если переел 2 дня подряд\n"
             "`/help` — эта справка\n\n"
             "⚖️ **Вес и прогресс:**\n"
             "В главном меню нажми «Вес/Прогресс»\n"
             "- Записать текущий вес\n"
             "- Прогресс за неделю\n"
             "- Прогресс за 3 недели\n"
             "- Вся история веса\n\n"
             "📅 **Автоматические уведомления:**\n"
             "- Каждое воскресенье в 10:00 — напоминание взвеситься\n"
             "- Каждые 3 недели — отчёт о прогрессе\n\n"
             "🍽 **Как добавлять еду:**\n"
             "Просто напиши: `гречка 100`, `курица 200`, `яблоко 150`\n"
             "Бот спросит способ приготовления.\n\n"
             "☕ **Напитки:**\n"
             "`кофе 100` — по умолчанию с молоком и сахаром (35 ккал)\n"
             "`кофе без молока 100` — без молока, с сахаром (22 ккал)\n"
             "`кофе без сахара 100` — с молоком, без сахара (15 ккал)\n"
             "`кофе черный 100` — чёрный кофе (2 ккал)\n"
             "`чай 150` — чёрный чай\n"
             "`чай с молоком 150` — с молоком\n"
             "`какао 100` — какао\n\n"
             "💧 **Вода:**\n"
             "`вода 500` — 500 мл\n"
             "`вода 1.5` — 1.5 литра\n\n"
             "📌 **Если продукт не найден:**\n"
             "- Попробуй написать на английском (`avocado`, `tofu`)\n"
             "- Или добавь вручную через `/add_my_product`"
    )

# --- ОБРАБОТЧИК МЕНЮ ---
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    
    if data == 'menu_add_food':
        await query.edit_message_text("🍽 Чтобы добавить еду, просто напиши:\n`название продукта вес`\nНапример: `гречка 100`, `курица 200`, `яблоко 150`\n\n☕ Для напитков: `кофе 100` (по умолчанию с молоком и сахаром)\nВарианты: `кофе без молока 100`, `кофе черный 100`\n\n💧 Для воды: `вода 500`")
        await context.bot.send_message(chat_id=chat_id, text="Выбери действие:", reply_markup=main_menu_keyboard())
    elif data == 'menu_water':
        await query.edit_message_text("💧 Чтобы добавить воду, напиши:\n`вода 500` — 500 мл\n`вода 1.5` — 1.5 литра")
        await context.bot.send_message(chat_id=chat_id, text="Выбери действие:", reply_markup=main_menu_keyboard())
    elif data == 'menu_stats':
        await query.edit_message_text("📊 Загружаю статистику... 🔄")
        await stats(update, context)
        await context.bot.send_message(chat_id=chat_id, text="Выбери действие:", reply_markup=main_menu_keyboard())
    elif data == 'menu_my_food':
        await query.edit_message_text("📋 Загружаю твои приёмы... 🔄")
        await my_food(update, context)
        await context.bot.send_message(chat_id=chat_id, text="Выбери действие:", reply_markup=main_menu_keyboard())
    elif data == 'menu_plan':
        await query.edit_message_text("📅 Генерирую план питания... 🔄")
        context.user_data['step'] = None
        await check_overeating(update, context)
    elif data == 'menu_history':
        await history(update, context)
    elif data == 'menu_weight':
        await weight_menu(update, context)
    elif data == 'weight_add':
        await weight_add(update, context)
    elif data == 'weight_week':
        await weight_week(update, context)
    elif data == 'weight_3weeks':
        await weight_3weeks(update, context)
    elif data == 'weight_history':
        await weight_history(update, context)
    elif data == 'menu_profile':
        await query.edit_message_text("⚙️ Загружаю профиль... 🔄")
        await profile(update, context)
        await context.bot.send_message(chat_id=chat_id, text="Выбери действие:", reply_markup=main_menu_keyboard())
    elif data == 'menu_help':
        await help_command(update, context)
        await context.bot.send_message(chat_id=chat_id, text="Выбери действие:", reply_markup=main_menu_keyboard())

async def send_daily_plan(app: Application):
    users = session.query(User).all()
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    
    for user in users:
        user_id = user.telegram_id
        meals = session.query(Meal).filter_by(user_id=user_id).filter(Meal.meal_time >= now - timedelta(days=2)).all()
        days_data = {}
        for meal in meals:
            day = meal.meal_time.date()
            days_data[day] = days_data.get(day, 0) + meal.calories
        
        overeat_days = []
        for day in [yesterday, day_before]:
            if day in days_data and days_data[day] > user.daily_calories:
                overeat_days.append(days_data[day] - user.daily_calories)
        
        if len(overeat_days) >= 2:
            await app.bot.send_message(chat_id=user_id, text="📅 Напоминание: у тебя было переедание 2 дня подряд. Воспользуйся командой /plan, чтобы получить персонализированный план питания на сегодня.")

# --- ЗАПУСК БОТА ---
def main():
    application = Application.builder().token(TOKEN).build()
    
    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start", "Приветствие"),
            BotCommand("profile", "Профиль"),
            BotCommand("add_my_product", "Добавить продукт"),
            BotCommand("my_food", "Мои приёмы"),
            BotCommand("stats", "Статистика"),
            BotCommand("plan", "План на завтра"),
            BotCommand("help", "Помощь"),
        ])
        
        scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
        scheduler.add_job(send_daily_plan, CronTrigger(hour=0, minute=0, timezone="Asia/Almaty"), args=[app])
        scheduler.add_job(send_weekly_reminder, CronTrigger(day_of_week='sun', hour=10, minute=0, timezone="Asia/Almaty"), args=[app])
        scheduler.add_job(send_3week_progress, CronTrigger(day_of_week='sun', hour=12, minute=0, timezone="Asia/Almaty"), args=[app])
        scheduler.start()
        print("⏰ Планировщик запущен!")
        print("📅 Ежедневные планы в 00:00")
        print("📅 Напоминание о весе каждое воскресенье в 10:00")
        print("📅 Отчёт за 3 недели каждое воскресенье в 12:00")
    
    application.post_init = post_init
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("add_my_product", add_my_product))
    application.add_handler(CommandHandler("my_food", my_food))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("plan", check_overeating))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(CallbackQueryHandler(handle_activity_choice, pattern='^[0-9.]+$'))
    application.add_handler(CallbackQueryHandler(handle_goal_choice, pattern='^(lose|maintain|gain)$'))
    application.add_handler(CallbackQueryHandler(delete_last_meal, pattern='^delete_last_meal$'))
    application.add_handler(CallbackQueryHandler(handle_cooking_method, pattern='^(raw|boiled|fried|deep_fried|baked|steamed)$'))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern='^menu_'))
    application.add_handler(CallbackQueryHandler(history_day, pattern='^history_day_'))
    application.add_handler(CallbackQueryHandler(weight_add, pattern='^weight_add$'))
    application.add_handler(CallbackQueryHandler(weight_week, pattern='^weight_week$'))
    application.add_handler(CallbackQueryHandler(weight_3weeks, pattern='^weight_3weeks$'))
    application.add_handler(CallbackQueryHandler(weight_history, pattern='^weight_history$'))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Бот запущен и готов к работе!")
    print("☕ По умолчанию: кофе 100 = с молоком и сахаром (35 ккал)")
    print("💧 Вода: вода 500")
    print("📋 Приёмы: /my_food")
    print("📅 План: /plan")
    print("📜 История: кнопка в меню")
    print("⚖️ Вес/Прогресс: кнопка в меню")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# ========== HEALTH CHECK ДЛЯ RENDER ==========
import asyncio
from aiohttp import web

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Health check server running on port {port}")
    # Держим сервер запущенным
    await asyncio.Event().wait()

def run_health_server():
    """Запускает health check сервер в отдельном потоке"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_health_server())

# Запускаем health check в фоновом потоке
if os.environ.get('RENDER', '') == 'true':
    import threading
    threading.Thread(target=run_health_server, daemon=True).start()
if __name__ == '__main__':
    main()