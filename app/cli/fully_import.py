# app/cli/full_import.py
import asyncio
import click
import subprocess
import logging

logger = logging.getLogger(__name__)

@click.command()
@click.option('--clean', is_flag=True, help='Start with clean database (drops existing tables)')
def full_import(clean):
    """Run a full import of all platform data in the correct order"""
    logging.basicConfig(level=logging.INFO)
    
    # List of commands to run in sequence
    commands = [
        # First create tables
        ["python", "-m", "app.cli.create_tables"],
        
        # Import eBay
        ["python", "-m", "app.cli.import_ebay"],
        
        # Import Reverb (add your username/password)
        ["python", "-m", "app.cli.import_reverb"],
        
        # Import Vintage & Rare (add your username/password)
        ["python", "-m", "app.cli.import_vr", "--username", "Musicground", "--password", "musicground1"],
        
        # Run product matching
        ["python", "-m", "app.cli.match_products", "--threshold", "0.75", "--commit"]
    ]
    
    # Run each command in sequence
    for cmd in commands:
        cmd_str = " ".join(cmd)
        logger.info(f"Running: {cmd_str}")
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            logger.error(f"Command failed with exit code {result.returncode}: {cmd_str}")
            return
        logger.info(f"Command completed successfully: {cmd_str}")
    
    logger.info("Full import completed successfully!")

if __name__ == "__main__":
    full_import()