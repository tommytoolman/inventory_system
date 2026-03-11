# In app/cli/__init__.py or your main CLI file
from app.cli.shipping import populate_shipping_profiles

def register_cli_commands(app):
    # Existing commands
    # ...
    
    @app.cli.command()
    def setup_shipping():
        """Setup shipping profiles."""
        import asyncio
        asyncio.run(populate_shipping_profiles(reset=False))
    
    @app.cli.command()
    def reset_shipping():
        """Reset and setup shipping profiles."""
        import asyncio
        asyncio.run(populate_shipping_profiles(reset=True))