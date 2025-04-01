# app/cli/update_status.py
import asyncio
import click
from sqlalchemy import text
from app.database import async_session

@click.command()
@click.option('--platform', type=click.Choice(['ebay', 'reverb', 'vintageandrare']), required=True)
@click.option('--external-id', required=True, help='External listing ID')
@click.option('--status', type=click.Choice(['ACTIVE', 'SOLD', 'ENDED', 'DRAFT']), required=True)
def update_status(platform, external_id, status):
    """Manually update the status of a listing"""
    
    async def _update():
        async with async_session() as session:
            async with session.begin():
                # Update platform_common status
                result = await session.execute(text("""
                    UPDATE platform_common
                    SET status = :status, 
                        manual_override = TRUE,
                        updated_at = NOW()
                    WHERE platform_name = :platform 
                    AND external_id = :external_id
                    RETURNING id
                """), {
                    "status": status,
                    "platform": platform,
                    "external_id": external_id
                })
                
                updated_id = result.scalar()
                if not updated_id:
                    print(f"No listing found for {platform} with ID {external_id}")
                    return
                
                print(f"Successfully updated {platform} listing {external_id} to {status}")
                
    asyncio.run(_update())

if __name__ == "__main__":
    update_status()