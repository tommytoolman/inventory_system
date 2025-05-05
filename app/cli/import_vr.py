# app/cli/import_vr.py
import asyncio
import logging
import click
import datetime
import sys
# Import the global session MAKER, not the session itself directly if passing
from app.database import async_session as global_async_session_maker
# Keep service import
from app.services.vintageandrare_service import VintageAndRareService
# Need AsyncSession for type hint
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

# --- Modify helper to ACCEPT session ---
async def _run_import_logic(session: AsyncSession, username: str, password: str, save_only: bool):
    """Contains the actual async import logic, using a provided session."""
    success = False
    stats = None
    try:
        # --- Use the PASSED session ---
        # Instantiate the service with the session
        vr_service = VintageAndRareService(db=session) # Pass the session
        # Call the service method to perform the import
        import_stats = await vr_service.run_import_process(username, password, save_only)

        # --- Explicit Commit (if needed, check service logic) ---
        # The service methods might already commit per row or use nested begins.
        # An outer commit might still be needed depending on transaction setup.
        # Let's assume commit is needed here for now, based on previous step.
        if import_stats and "error" not in import_stats:
            print("Attempting final commit (inside _run_import_logic)...")
            await session.commit() # <<< COMMIT THE PASSED SESSION
            print("Commit successful (inside _run_import_logic).")
            success = True
            stats = import_stats
        elif import_stats and "error" in import_stats:
            logger.error(f"Import failed: {import_stats['error']}")
            success = False
            stats = import_stats
            # If service reported error, likely rollback happened or is needed
            await session.rollback()
        else:
            logger.error("Import process did not return statistics.")
            success = False
            stats = None
            # Rollback might be appropriate here too
            await session.rollback()

        # Log summary
        if stats:
            # ... (logging as before) ...
            pass

    except Exception as e:
        # Handle exceptions that might occur OUTSIDE the service call but within the session block
        logger.exception("Critical error during async import execution wrapper")
        success = False
        stats = {"error": f"Wrapper Error: {str(e)}"}
        # Rollback on exception
        await session.rollback() # Explicit rollback on error

    return success, stats

@click.command()
@click.option('--username', required=True, help='VintageAndRare username', envvar='VINTAGE_AND_RARE_USERNAME')
@click.option('--password', required=True, help='VintageAndRare password', envvar='VINTAGE_AND_RARE_PASSWORD')
@click.option('--save-only', is_flag=True, help='Only save CSV without importing')
async def import_vr(username, password, save_only):
    """Downloads (scrapes) and imports Vintage & Rare listings into the database."""
    start_time = datetime.datetime.now()
    logger.info(f"Starting Vintage & Rare import process via CLI at {start_time}")

    # --- Create session here for normal execution ---
    async with global_async_session_maker() as session: # Use the global maker
        try:
            # --- Pass the created session to the logic function ---
            success, stats = await _run_import_logic(session, username, password, save_only)
            # --- ---

            if not success:
                error_msg = stats.get('error', 'Unknown error during import.') if stats else 'Unknown error during import.'
                click.echo(f"Error: {error_msg}", err=True)
                sys.exit(1)

        except Exception as e:
            # Catch errors during session creation or the logic call itself
            logger.exception("Critical error running import command")
            click.echo(f"Critical Error: {str(e)}", err=True)
            sys.exit(1)

    end_time = datetime.datetime.now()
    duration = end_time - start_time
    logger.info(f"Completed Vintage & Rare import process via CLI in {duration}")


# Keep this block for direct script execution if needed
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    import_vr()