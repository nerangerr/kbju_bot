import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    try:
        conn.execute(text('ALTER TABLE daily_plans ADD COLUMN target_calories INTEGER'))
        conn.commit()
        print('✅ Колонка target_calories успешно добавлена!')
    except Exception as e:
        if 'duplicate column name' in str(e).lower() or 'already exists' in str(e).lower():
            print('ℹ️ Колонка target_calories уже существует!')
        else:
            print(f'❌ Ошибка: {e}')