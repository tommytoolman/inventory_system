from dotenv import load_dotenv
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from .env file
load_dotenv()

# Import database setup
# from app.database import engine, Base, get_session
# from app.core.config import get_settings

# # Create tables in the database (if they don't exist)
# # Base.metadata.create_all(bind=engine)

# def create_app() -> FastAPI:
#     """Create and configure the FastAPI application"""
#     app = FastAPI(
#         title="Inventory System API",
#         description="API for inventory management and shipping",
#         version="1.0.0",
#     )
    
#     # Configure CORS
#     app.add_middleware(
#         CORSMiddleware,
#         allow_origins=["*"],  # In production, replace with specific origins
#         allow_credentials=True,
#         allow_methods=["*"],
#         allow_headers=["*"],
#     )
    
#     return app

# app = create_app()

# # from app.routes import shipping