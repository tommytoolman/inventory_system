# app/routes/settings.py
"""
Settings routes for platform visibility preferences.

Users can show/hide individual platforms from their dashboard and menus.
Hidden platforms still sync in the background and data remains accessible via API.
"""

import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.database import async_session
from app.core.templates import templates
from app.core.security import get_current_username
from app.models.platform_preference import PlatformPreference

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


async def get_user_preferences(username: str) -> PlatformPreference:
    """Get or create platform preferences for a user.

    Returns a PlatformPreference with all platforms visible by default.
    """
    async with async_session() as db:
        result = await db.execute(
            select(PlatformPreference).where(PlatformPreference.username == username)
        )
        prefs = result.scalar_one_or_none()

        if prefs is None:
            prefs = PlatformPreference(username=username)
            db.add(prefs)
            await db.commit()
            await db.refresh(prefs)

        return prefs


async def get_visible_platforms(username: str) -> list:
    """Get the list of platform slugs visible to a user.

    Convenience wrapper used by dashboard, templates, and reports.
    """
    prefs = await get_user_preferences(username)
    return prefs.get_visible_platforms()


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, username: str = Depends(get_current_username)):
    """Render the settings page."""
    prefs = await get_user_preferences(username)

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "preferences": prefs.to_dict(),
        "username": username,
    })


@router.post("/platform-visibility")
async def update_platform_visibility(
    request: Request,
    username: str = Depends(get_current_username),
):
    """Save platform visibility preferences from form submission."""
    form = await request.form()

    async with async_session() as db:
        result = await db.execute(
            select(PlatformPreference).where(PlatformPreference.username == username)
        )
        prefs = result.scalar_one_or_none()

        if prefs is None:
            prefs = PlatformPreference(username=username)
            db.add(prefs)

        # Checkboxes only send value when checked; absent = unchecked
        prefs.show_ebay = "show_ebay" in form
        prefs.show_reverb = "show_reverb" in form
        prefs.show_shopify = "show_shopify" in form
        prefs.show_vintage_rare = "show_vintage_rare" in form
        prefs.show_woocommerce = "show_woocommerce" in form

        await db.commit()

    logger.info("Updated platform visibility for user %s", username)
    return RedirectResponse(url="/settings", status_code=303)
