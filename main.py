from dotenv import load_dotenv

from app.server import create_app

load_dotenv()

app = create_app()

