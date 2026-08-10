import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    try:
        conn.execute(text('ALTER TABLE daily_plans ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP'))
        conn.commit()
        print('✅ Колонка created_at успешно добавлена!')
    except Exception as e:
        if 'duplicate column name' in str(e).lower() or 'already exists' in str(e).lower():
            print('ℹ️ Колонка created_at уже существует!')
        else:
            print(f'❌ Ошибка: {e}')