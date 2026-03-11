#!/usr/bin/env python3
"""
Generate RIFF Developer Onboarding Pack PDF
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    Image, KeepTogether, ListFlowable, ListItem, Preformatted
)
from reportlab.pdfgen import canvas
from datetime import datetime
from pathlib import Path

# RIFF Brand Colors
COLORS = {
    'primary_text': colors.HexColor('#1F2937'),  # Gray-800
    'secondary_text': colors.HexColor('#6B7280'),  # Gray-500
    'accent': colors.HexColor('#059669'),  # Green-600
    'background': colors.HexColor('#F3F4F6'),  # Gray-100
    'border': colors.HexColor('#D1D5DB'),  # Gray-300
    # Platform colors
    'reverb': colors.HexColor('#FF5A00'),
    'ebay': colors.HexColor('#0064D2'),
    'shopify': colors.HexColor('#95BF47'),
    'vr': colors.HexColor('#6B46C1'),
    'dropbox': colors.HexColor('#0061FF'),
    'dhl_red': colors.HexColor('#D40511'),
    'dhl_yellow': colors.HexColor('#FFCC00'),
}

class NumberedCanvas(canvas.Canvas):
    """Custom canvas for page numbers and footer"""
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_footer(self, page_count):
        self.saveState()
        self.setFont('Helvetica', 9)
        self.setFillColor(COLORS['secondary_text'])
        page_num = self._pageNumber
        text = f"Page {page_num} of {page_count}"
        self.drawCentredString(letter[0] / 2.0, 0.5 * inch, text)
        self.drawCentredString(letter[0] / 2.0, 0.35 * inch,
                              "RIFF - Realtime Inventory Fast Flow")
        self.restoreState()


def create_styles():
    """Create custom paragraph styles"""
    styles = getSampleStyleSheet()

    # Title
    styles.add(ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=COLORS['primary_text'],
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))

    # Section Header
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=COLORS['accent'],
        spaceAfter=12,
        spaceBefore=20,
        fontName='Helvetica-Bold',
        borderColor=COLORS['accent'],
        borderWidth=0,
        borderPadding=0,
        leftIndent=0,
    ))

    # Subsection
    styles.add(ParagraphStyle(
        name='Subsection',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=COLORS['primary_text'],
        spaceAfter=8,
        spaceBefore=12,
        fontName='Helvetica-Bold'
    ))

    # Body
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=COLORS['primary_text'],
        spaceAfter=8,
        alignment=TA_JUSTIFY,
        leading=14
    ))

    # Bullet
    styles.add(ParagraphStyle(
        name='CustomBullet',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=COLORS['primary_text'],
        spaceAfter=4,
        leftIndent=20,
        bulletIndent=10,
        leading=13
    ))

    # Small caption
    styles.add(ParagraphStyle(
        name='Caption',
        parent=styles['BodyText'],
        fontSize=8,
        textColor=COLORS['secondary_text'],
        spaceAfter=4,
        alignment=TA_CENTER
    ))

    # Custom Code style
    styles.add(ParagraphStyle(
        name='CustomCode',
        parent=styles['Code'],
        fontSize=9,
        textColor=COLORS['primary_text'],
        backColor=COLORS['background'],
        leftIndent=10,
        rightIndent=10,
        spaceAfter=8,
        spaceBefore=4
    ))

    return styles


def create_cover_page(styles):
    """Create cover page elements"""
    story = []

    # Logo
    logo_path = Path(__file__).parent.parent / "app/static/images/riff_logo.png"
    if logo_path.exists():
        img = Image(str(logo_path), width=2*inch, height=2*inch)
        story.append(Spacer(1, 1.5*inch))
        story.append(img)

    story.append(Spacer(1, 0.5*inch))

    # Title
    story.append(Paragraph("RIFF Developer<br/>Onboarding Pack", styles['CustomTitle']))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("<i>Realtime Inventory Fast Flow</i>", styles['Caption']))
    story.append(Spacer(1, 1*inch))

    # Subtitle box
    subtitle_data = [[Paragraph(
        "<b>Technical Documentation for Developers</b><br/>"
        "System Architecture, Tech Stack, and Getting Started Guide",
        ParagraphStyle('centered_body',
                      parent=styles['CustomBody'],
                      alignment=TA_CENTER,
                      fontSize=11)
    )]]

    subtitle_table = Table(subtitle_data, colWidths=[5*inch])
    subtitle_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
        ('BOX', (0, 0), (-1, -1), 1, COLORS['border']),
        ('PADDING', (0, 0), (-1, -1), 15),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(subtitle_table)

    story.append(Spacer(1, 1*inch))

    # Version info
    story.append(Paragraph(
        f"<b>Version:</b> 1.0<br/>"
        f"<b>Last Updated:</b> {datetime.now().strftime('%B %d, %Y')}<br/>"
        f"<b>Prepared For:</b> New Developer Onboarding",
        ParagraphStyle('info_style',
                      parent=styles['Caption'],
                      fontSize=9,
                      alignment=TA_CENTER)
    ))

    story.append(PageBreak())
    return story


def create_executive_summary(styles):
    """Section 1: Executive Summary"""
    story = []

    story.append(Paragraph("Executive Summary", styles['SectionHeader']))

    story.append(Paragraph(
        "<b>What is RIFF?</b> RIFF (Realtime Inventory Fast Flow) is a multi-platform inventory management "
        "system built for music gear retailers. It synchronizes product listings across Reverb, eBay, Shopify, "
        "and Vintage & Rare from a single source of truth.",
        styles['CustomBody']
    ))

    story.append(Paragraph(
        "<b>Core Problem:</b> Music gear retailers manually copy listings across multiple marketplaces, leading "
        "to inconsistent data, overselling, and hours of tedious work.",
        styles['CustomBody']
    ))

    story.append(Paragraph(
        "<b>The Solution:</b> Create once, sync everywhere. RIFF maintains a canonical product database and "
        "automatically propagates changes (price, quantity, description) to all connected platforms within minutes.",
        styles['CustomBody']
    ))

    # Key metrics table
    metrics_data = [
        ["Metric", "Value"],
        ["Active Listings Managed", "~500+"],
        ["Platforms Supported", "4 (Reverb, eBay, Shopify, V&R)"],
        ["Sync Frequency", "Push (immediate) + Hourly pull"],
        ["Order Processing", "Real-time inventory updates"],
        ["Deployment", "Railway.app (Docker)"],
        ["Tech Stack", "Python 3.12, FastAPI, PostgreSQL"],
    ]

    metrics_table = Table(metrics_data, colWidths=[3*inch, 2.5*inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['accent']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))

    story.append(Spacer(1, 0.2*inch))
    story.append(metrics_table)

    story.append(PageBreak())
    return story


def create_functions_section(styles):
    """Section 2: Core Functions"""
    story = []

    story.append(Paragraph("Core Functions & Features", styles['SectionHeader']))

    functions = [
        {
            "name": "Product Management",
            "desc": "CRUD operations for product catalog with SKU generation, category mapping, and image handling",
            "value": "Single source of truth for all product data",
            "example": "Create a vintage Fender guitar once, automatically generates SKU (REV-12345), extracts metadata"
        },
        {
            "name": "Multi-Platform Sync",
            "desc": "Bidirectional synchronization with Reverb, eBay, Shopify, and Vintage & Rare marketplaces",
            "value": "Eliminates manual copying, ensures consistency across platforms",
            "example": "Update price to £1,200 → triggers immediate push sync to all 4 platforms via API"
        },
        {
            "name": "Order Processing",
            "desc": "Captures sales from all platforms and automatically updates inventory quantities",
            "value": "Prevents overselling, maintains accurate stock levels",
            "example": "Item sells on Reverb → quantity decrements on eBay, Shopify, and V&R automatically"
        },
        {
            "name": "Inventory Reconciliation",
            "desc": "Detects discrepancies between local database and platform quantities",
            "value": "Catches manual edits, API failures, or sync issues",
            "example": "Reports show Shopify quantity is 2 but local DB shows 1 → flags for manual review"
        },
        {
            "name": "Sync Event Management",
            "desc": "Tracks all changes as events (create, update, archive) with retry logic for failures",
            "value": "Audit trail, error recovery, visibility into what's happening",
            "example": "eBay API returns 429 rate limit → event stays 'pending', retries automatically"
        },
        {
            "name": "Image Management",
            "desc": "CDN optimization via Dropbox, lazy loading, and automatic repair of broken image URLs",
            "value": "98% bandwidth savings, fast page loads, broken image auto-fix",
            "example": "Nightly job detects 401 errors, refreshes 615 images from Reverb API"
        },
        {
            "name": "Reporting & Analytics",
            "desc": "Sync history, platform coverage, non-performing inventory, engagement metrics",
            "value": "Data-driven decisions, identify bottlenecks",
            "example": "Shows 85% of inventory on all 4 platforms, 15% missing from V&R"
        },
        {
            "name": "Shipping Integration",
            "desc": "DHL API for label generation and tracking (85% complete)",
            "value": "One-click shipping labels, automatic tracking updates",
            "example": "Order #1234 → generate DHL label, email customer tracking number"
        },
    ]

    for func in functions:
        # Function name with colored bar
        func_title = f"<b>{func['name']}</b>"
        story.append(Paragraph(func_title, styles['Subsection']))

        # Description
        story.append(Paragraph(f"<b>Description:</b> {func['desc']}", styles['CustomBody']))

        # Value
        story.append(Paragraph(f"<b>User Value:</b> {func['value']}", styles['CustomBody']))

        # Example (in gray box)
        example_data = [[Paragraph(f"<i>Example:</i> {func['example']}",
                                  ParagraphStyle('example', parent=styles['CustomBody'], fontSize=9))]]
        example_table = Table(example_data, colWidths=[5.5*inch])
        example_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
            ('BOX', (0, 0), (-1, -1), 0.5, COLORS['border']),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(example_table)
        story.append(Spacer(1, 0.1*inch))

    story.append(PageBreak())
    return story


def create_highlevel_stack(styles):
    """Section 3: High-Level Tech Stack"""
    story = []

    story.append(Paragraph("High-Level Tech Stack", styles['SectionHeader']))

    story.append(Paragraph(
        "RIFF is built with modern Python async frameworks, deployed as Docker containers on Railway.app. "
        "The architecture follows a service-oriented pattern with FastAPI handling HTTP requests, SQLAlchemy "
        "managing database interactions, and platform-specific services handling API integrations.",
        styles['CustomBody']
    ))

    # Architecture diagram (text-based)
    arch_text = """
    <b>Request Flow:</b>

    User Browser (Jinja2 + Vanilla JS + TailwindCSS)
            ↓
    FastAPI Routes (/inventory, /reports, /orders)
            ↓
    Service Layer (ebay_service, reverb_service, shopify_service, vr_service)
            ↓
    Database Layer (SQLAlchemy ORM → PostgreSQL)
            ↓
    External APIs (Reverb API, eBay Trading API, Shopify GraphQL, V&R Selenium)

    <b>Background Jobs:</b>
    Custom Async Scheduler → Hourly Sync Jobs → Platform APIs → Database Updates
    """

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(arch_text, styles['CustomCode']))

    # Core components table
    story.append(Paragraph("<b>Core Components:</b>", styles['Subsection']))

    components_data = [
        ["Component", "Technology", "Purpose"],
        ["Backend Framework", "FastAPI 0.115.8", "Async web framework with auto-docs"],
        ["Database", "PostgreSQL", "Relational data storage"],
        ["ORM", "SQLAlchemy 2.0.37", "Database abstraction layer"],
        ["Frontend", "Jinja2 + Vanilla JS", "Server-side rendering"],
        ["Styling", "TailwindCSS (CDN)", "Utility-first CSS"],
        ["Deployment", "Docker + Railway.app", "Containerized PaaS hosting"],
        ["Background Jobs", "Custom async scheduler", "Hourly syncs, daily stats"],
    ]

    components_table = Table(components_data, colWidths=[1.5*inch, 2*inch, 2.5*inch])
    components_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['accent']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    story.append(components_table)

    story.append(PageBreak())
    return story


def create_detailed_stack(styles):
    """Section 4: Detailed Tech Stack"""
    story = []

    story.append(Paragraph("Detailed Tech Stack Reference", styles['SectionHeader']))

    story.append(Paragraph(
        "This section provides a comprehensive inventory of all technologies, libraries, and services used in RIFF. "
        "Each component includes a one-sentence description of its purpose.",
        styles['CustomBody']
    ))

    # Core Framework section
    story.append(Paragraph("Core Framework", styles['Subsection']))
    core_components = [
        ["FastAPI 0.115.8", "Modern async Python web framework with automatic OpenAPI documentation"],
        ["Uvicorn 0.34.0", "Lightning-fast ASGI server for running async Python web applications"],
        ["Python 3.12", "Latest stable Python runtime with enhanced async performance and type hints"],
    ]
    story.extend(create_component_table(core_components, styles))

    # Database Layer
    story.append(Paragraph("Database Layer", styles['Subsection']))
    db_components = [
        ["PostgreSQL", "Production-grade relational database for structured inventory and sync data"],
        ["SQLAlchemy 2.0.37", "Python ORM enabling type-safe async database queries with relationship mapping"],
        ["Alembic 1.14.1", "Database migration tool for version-controlled schema changes"],
        ["asyncpg 0.30.0", "High-performance async PostgreSQL driver for SQLAlchemy"],
        ["psycopg2-binary 2.9.9", "Sync PostgreSQL driver for migration scripts and standalone tools"],
    ]
    story.extend(create_component_table(db_components, styles))

    # Frontend
    story.append(Paragraph("Frontend", styles['Subsection']))
    frontend_components = [
        ["Jinja2 3.1.4", "Server-side HTML templating engine for dynamic page generation"],
        ["TailwindCSS (CDN)", "Utility-first CSS framework loaded via CDN (no build step required)"],
        ["Vanilla JavaScript", "Single 500-line class-based JS file for UI interactions (no frameworks)"],
        ["Inline CSS", "Custom styles in template <style> blocks for component-specific styling"],
    ]
    story.extend(create_component_table(frontend_components, styles))

    story.append(PageBreak())

    # Platform Integrations
    story.append(Paragraph("Platform Integrations", styles['Subsection']))

    # Reverb
    story.append(Paragraph("<font color='#FF5A00'><b>Reverb Integration</b></font>",
                          ParagraphStyle('platform_header', parent=styles['CustomBody'], fontSize=11)))
    reverb_components = [
        ["Custom REST Client", "httpx-based async client for Reverb API v3 (RESTful JSON)"],
        ["Personal Access Token", "Bearer token authentication for API requests"],
        ["WebSocket Support", "Planned real-time order notifications via WebSocket connection"],
    ]
    story.extend(create_component_table(reverb_components, styles))

    # eBay
    story.append(Paragraph("<font color='#0064D2'><b>eBay Integration</b></font>",
                          ParagraphStyle('platform_header', parent=styles['CustomBody'], fontSize=11)))
    ebay_components = [
        ["ebaysdk 2.2.0", "Official eBay Python SDK for Trading API access"],
        ["Trading API (XML)", "Legacy XML-based API for listing creation and management"],
        ["OAuth 2.0", "Three-legged OAuth flow with encrypted refresh token storage"],
        ["Item Specifics System", "Category-specific required fields for listing compliance"],
        ["Shipping Profiles", "Business policies for consistent shipping across listings"],
    ]
    story.extend(create_component_table(ebay_components, styles))

    # Shopify
    story.append(Paragraph("<font color='#95BF47'><b>Shopify Integration</b></font>",
                          ParagraphStyle('platform_header', parent=styles['CustomBody'], fontSize=11)))
    shopify_components = [
        ["GraphQL API 2024-01", "Modern GraphQL-based Admin API for store management"],
        ["Custom Python Client", "httpx-based async client with GraphQL query builder"],
        ["App Authentication", "Custom app with scoped access token per store"],
        ["Inventory Location API", "Multi-location inventory tracking and updates"],
        ["Metafields", "Custom product attributes for extended data and SEO optimization"],
    ]
    story.extend(create_component_table(shopify_components, styles))

    # V&R
    story.append(Paragraph("<font color='#6B46C1'><b>Vintage & Rare Integration</b></font>",
                          ParagraphStyle('platform_header', parent=styles['CustomBody'], fontSize=11)))
    vr_components = [
        ["Selenium 4.21.0", "Browser automation for web scraping (no public API available)"],
        ["undetected-chromedriver 3.5.5", "Cloudflare bypass for bot detection evasion"],
        ["BeautifulSoup4 4.12.3", "HTML parsing for extracting listing data from scraped pages"],
        ["curl_cffi", "TLS fingerprint matching library for advanced scraping"],
    ]
    story.extend(create_component_table(vr_components, styles))

    story.append(PageBreak())

    # Additional Services
    story.append(Paragraph("Additional Services", styles['Subsection']))

    # Dropbox
    story.append(Paragraph("<font color='#0061FF'><b>Dropbox (Image Storage)</b></font>",
                          ParagraphStyle('platform_header', parent=styles['CustomBody'], fontSize=11)))
    dropbox_components = [
        ["Dropbox SDK 12.0.2", "Cloud storage integration for product image hosting"],
        ["Thumbnail API", "Bandwidth optimization via thumbnail URLs (~98% size reduction)"],
        ["Lazy Loading", "Full-resolution images fetched only when user selects them"],
        ["Token Refresh", "Automatic OAuth token renewal for uninterrupted access"],
    ]
    story.extend(create_component_table(dropbox_components, styles))

    # DHL
    story.append(Paragraph("<font color='#D40511'><b>DHL (Shipping)</b></font>",
                          ParagraphStyle('platform_header', parent=styles['CustomBody'], fontSize=11)))
    dhl_components = [
        ["DHL Express API", "Label generation and tracking for international shipments (85% complete)"],
        ["reportlab 4.0.8", "PDF generation for shipping labels and commercial invoices"],
    ]
    story.extend(create_component_table(dhl_components, styles))

    # Data Processing
    story.append(Paragraph("Data Processing", styles['Subsection']))
    data_components = [
        ["pandas 2.2.2", "CSV import/export, data transformations, and bulk operations"],
        ["numpy 1.26.4", "Numerical operations for data analysis and statistics"],
        ["fuzzywuzzy 0.18.0", "Fuzzy string matching for duplicate product detection"],
        ["python-Levenshtein 0.25.1", "Fast edit distance calculations for string similarity"],
    ]
    story.extend(create_component_table(data_components, styles))

    # HTTP & Async
    story.append(Paragraph("HTTP & Async Libraries", styles['Subsection']))
    http_components = [
        ["httpx 0.27.0", "Async HTTP client for all platform API calls (primary client)"],
        ["aiohttp 3.9.5", "Alternative async HTTP client for specific use cases"],
        ["requests 2.32.3", "Synchronous HTTP client for legacy scripts and migrations"],
        ["aiofiles 24.1.0", "Async file I/O operations for image uploads and CSV processing"],
    ]
    story.extend(create_component_table(http_components, styles))

    # Background Jobs
    story.append(Paragraph("Background Jobs & Scheduling", styles['Subsection']))
    job_components = [
        ["Custom Scheduler", "scripts/run_sync_scheduler.py - interval-based job scheduling without Celery"],
        ["asyncio", "Native Python async primitives for concurrent operations"],
        ["Per-Platform Jobs", "Hourly sync jobs for Reverb, eBay, Shopify, V&R (cron: */60 * * * *)"],
        ["Stats Collection", "Daily statistics aggregation job (cron: 0 2 * * *)"],
        ["Auto-Archive", "Weekly Shopify archive cleanup job (cron: 0 3 * * 0)"],
    ]
    story.extend(create_component_table(job_components, styles))

    story.append(PageBreak())

    # Configuration & Validation
    story.append(Paragraph("Configuration & Validation", styles['Subsection']))
    config_components = [
        ["pydantic-settings 2.7.1", "Type-safe settings management from environment variables"],
        ["python-dotenv 1.0.1", "Loading environment variables from .env files for local development"],
        ["Pydantic 2.9.1", "Data validation and serialization with type hints"],
    ]
    story.extend(create_component_table(config_components, styles))

    # Testing
    story.append(Paragraph("Testing", styles['Subsection']))
    test_components = [
        ["pytest", "Test framework for unit and integration tests (200+ tests)"],
        ["pytest-asyncio", "Async test support for FastAPI routes and services"],
        ["pytest-mock", "Mocking utilities for isolating units under test"],
    ]
    story.extend(create_component_table(test_components, styles))

    # Utilities
    story.append(Paragraph("Utilities", styles['Subsection']))
    util_components = [
        ["xmltodict 0.13.0", "XML to dictionary conversion for eBay API responses"],
        ["iso8601 2.1.0", "ISO 8601 date/time parsing for platform timestamps"],
        ["tabulate 0.9.0", "CLI table formatting for script output"],
        ["Pillow 10.4.0", "Image processing for resizing and format conversion"],
    ]
    story.extend(create_component_table(util_components, styles))

    # Deployment
    story.append(Paragraph("Deployment & Infrastructure", styles['Subsection']))
    deploy_components = [
        ["Docker", "Containerized deployment with Python 3.12-slim base image"],
        ["Railway.app", "Production PaaS hosting with auto-deploy from GitHub main branch"],
        ["PostgreSQL Addon", "Managed PostgreSQL database provided by Railway"],
        ["Chrome Service", "Separate Railway service for Selenium/ChromeDriver (V&R scraping)"],
        ["VR Service", "Dedicated service for V&R sync jobs (isolated from main app)"],
    ]
    story.extend(create_component_table(deploy_components, styles))

    # Monitoring
    story.append(Paragraph("Monitoring & Logging", styles['Subsection']))
    monitoring_components = [
        ["Python logging", "Structured logging with configurable levels (INFO, WARNING, ERROR)"],
        ["Activity Logger", "Custom service for user-facing audit trail of all actions"],
        ["Railway Logs", "Centralized log aggregation and search in Railway dashboard"],
    ]
    story.extend(create_component_table(monitoring_components, styles))

    story.append(PageBreak())
    return story


def create_component_table(components, styles):
    """Helper to create component tables"""
    from xml.sax.saxutils import escape
    story = []
    table_data = []

    for component, description in components:
        # Escape HTML characters but allow formatting tags
        safe_desc = description.replace('<', '&lt;').replace('>', '&gt;')
        table_data.append([
            Paragraph(f"<b>{component}</b>", ParagraphStyle('comp_name', parent=styles['CustomBody'], fontSize=9)),
            Paragraph(safe_desc, ParagraphStyle('comp_desc', parent=styles['CustomBody'], fontSize=9))
        ])

    if table_data:
        comp_table = Table(table_data, colWidths=[1.8*inch, 4.2*inch])
        comp_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
        ]))
        story.append(comp_table)
        story.append(Spacer(1, 0.1*inch))

    return story


def create_architecture_diagram(styles):
    """Section 5: System Architecture Diagram"""
    story = []

    story.append(Paragraph("System Architecture", styles['SectionHeader']))

    story.append(Paragraph(
        "RIFF follows a layered architecture with clear separation of concerns. The diagram below shows "
        "the complete system including all services, external integrations, and data flow.",
        styles['CustomBody']
    ))

    # Full architecture diagram - using simple text formatting
    arch_diagram = """
    ========================================================================
                              USER BROWSER
              (Jinja2 Templates + Vanilla JS + TailwindCSS)
    ========================================================================
                                    |
                             HTTP Requests
                                    |
                                    v
    ========================================================================
                          FASTAPI APPLICATION
    ------------------------------------------------------------------------
      Routes Layer
        • /inventory (list, detail, add, edit)
        • /reports (sync events, reconciliation, analytics)
        • /orders (list, process, ship)
        • /platforms/{reverb,ebay,shopify,vr}
    ------------------------------------------------------------------------
      Service Layer
        • reverb_service.py (130KB)
        • ebay_service.py (128KB)
        • shopify_service.py (100KB)
        • vr_service.py
        • event_processor.py (sync events)
        • order_sale_processor.py (orders to inventory)
    ========================================================================
                                    |
                    +---------------+---------------+
                    |               |               |
                    v               v               v
          [PostgreSQL Database] [Background Jobs] [External Services]
              • products            Cron Jobs:        • Dropbox
              • platform_common     • Hourly Sync     • DHL API
              • reverb_listings     • Daily Stats
              • ebay_listings       • Weekly Archive
              • shopify_listings    • Nightly Images
              • vr_listings
              • sync_events
              • orders
                    |
                    |
        +-----------+-----------+-----------+-----------+
        |           |           |           |
        v           v           v           v
    [Reverb]    [eBay]     [Shopify]    [V&R]
     REST API   Trading    GraphQL      Selenium
     JSON       API (XML)  API          Scraping
                OAuth2     OAuth2       Username/Pass

    <b>Railway Services (Production Infrastructure):</b>
    ------------------------------------------------------------------------
      • Core App (FastAPI) - Port 8000
      • PostgreSQL Database
      • Chrome Service (Selenium for V&R)
      • VR Service (Isolated)
      • Background Scheduler (Separate process)
    ------------------------------------------------------------------------

    <b>Cron Schedule:</b>
      • Hourly Sync:     */60 * * * *  (All platforms)
      • Daily Stats:     0 2 * * *     (Statistics aggregation)
      • Weekly Archive:  0 3 * * 0     (Shopify cleanup)
      • Nightly Images:  0 2 * * *     (Broken image repair)
    """

    story.append(Spacer(1, 0.15*inch))
    diagram_style = ParagraphStyle(
        'diagram',
        parent=styles['CustomCode'],
        fontSize=6.5,
        fontName='Courier',
        leading=8,
        leftIndent=2,
        rightIndent=2
    )
    story.append(Preformatted(arch_diagram, diagram_style))

    story.append(PageBreak())
    return story


def create_database_schema(styles):
    """Database schema section"""
    story = []

    story.append(Paragraph("Database Schema Overview", styles['SectionHeader']))

    story.append(Paragraph(
        "RIFF uses a schema-per-platform approach where each marketplace gets a dedicated table for "
        "platform-specific fields, linked via the platform_common bridge table.",
        styles['CustomBody']
    ))

    schema_diagram = """
    products (core inventory - source of truth)
      - id (PK)
      - sku (REV-12345, EBY-67890, SHOP-11111, VR-22222)
      - brand, model, category
      - base_price, quantity
      - primary_image, additional_images (JSONB)
      - description, condition
      - processing_time (days)

              | (1:many)
              v
    platform_common (linkage table)
      - id (PK)
      - product_id (FK -> products.id)
      - platform_name ('reverb', 'ebay', 'shopify', 'vr')
      - external_id (platform's listing ID)
      - status ('active', 'ended', 'pending')
      - created_at, updated_at

              |
      +-------+-------+-------+-------+
      |       |       |       |       |
      v       v       v       v       v
    [reverb] [ebay]  [shopify] [vr]  [sync_events]
    listings listings listings listings (changes)

    reverb_listings:        ebay_listings:          sync_events:
    - platform_id (FK)      - platform_id (FK)      - id
    - reverb_listing_id     - ebay_item_id          - product_id
    - extended_attributes   - category_id           - platform_name
      (JSONB)               - title                 - event_type
                            - shipping_profile_id   - status (pending/
    shopify_listings:                                 completed/failed)
    - platform_id (FK)      vr_listings:            - data (JSONB)
    - shopify_product_id    - platform_id (FK)      - created_at
    - extended_attributes   - vr_listing_id
      (JSONB)               - extended_attributes
                              (JSONB)

    <b>Order Tables (per platform):</b>
    reverb_orders, ebay_orders, shopify_orders
      - order_number, order_uuid
      - buyer_name, buyer_email
      - total_amount, payment_status
      - shipping_address, tracking_number
      - processed (bool) -> triggers inventory decrement
    """

    story.append(Spacer(1, 0.1*inch))
    schema_style = ParagraphStyle(
        'schema',
        parent=styles['CustomCode'],
        fontSize=7,
        fontName='Courier',
        leading=9,
        leftIndent=2,
        rightIndent=2
    )
    story.append(Preformatted(schema_diagram, schema_style))

    story.append(PageBreak())
    return story


def create_getting_started(styles):
    """Getting started section"""
    story = []

    story.append(Paragraph("Getting Started Guide", styles['SectionHeader']))

    story.append(Paragraph(
        "This section walks through setting up your local development environment and making your first change.",
        styles['CustomBody']
    ))

    # Prerequisites
    story.append(Paragraph("Prerequisites", styles['Subsection']))
    prereqs = [
        "Python 3.12+ installed (check with <font face='Courier'>python3 --version</font>)",
        "PostgreSQL 14+ installed (or Docker for database)",
        "Git version control",
        "Basic understanding of async/await in Python",
        "Familiarity with SQL and REST APIs",
    ]
    for prereq in prereqs:
        story.append(Paragraph(f"• {prereq}", styles['CustomBullet']))

    story.append(Spacer(1, 0.1*inch))

    # Setup steps
    story.append(Paragraph("Local Environment Setup", styles['Subsection']))

    setup_code = """
# 1. Clone repository
git clone https://github.com/tommytoolman/inventory_system.git
cd inventory_system

# 2. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create database
createdb riff_inventory_dev

# 5. Configure environment
cp .env.example .env
# Edit .env with your database URL:
# DATABASE_URL=postgresql+asyncpg://localhost/riff_inventory_dev

# 6. Run migrations
alembic upgrade head

# 7. Start development server
uvicorn app.main:app --reload --port 8000

# 8. Visit http://localhost:8000
    """

    story.append(Paragraph(
        f"<font face='Courier' size='8'>{setup_code}</font>",
        ParagraphStyle('setup',
                      parent=styles['CustomCode'],
                      fontSize=8,
                      fontName='Courier',
                      leading=11)
    ))

    # Next Steps
    story.append(Paragraph("Next Steps", styles['Subsection']))
    next_steps = [
        "Read <b>docs/todo.md</b> for current priorities and context",
        "Browse <b>app/models/</b> to understand the data model",
        "Run tests with <font face='Courier'>pytest tests/ -v</font>",
        "Create a test product via the UI and trace the code path",
        "Pick a starter task from todo.md and create a branch",
        "Ask questions! The codebase is well-documented.",
    ]
    for step in next_steps:
        story.append(Paragraph(f"• {step}", styles['CustomBullet']))

    story.append(PageBreak())
    return story


def create_key_patterns(styles):
    """Key patterns and gotchas"""
    story = []

    story.append(Paragraph("Key Patterns & Gotchas", styles['SectionHeader']))

    story.append(Paragraph(
        "Common patterns you'll encounter and mistakes to avoid.",
        styles['CustomBody']
    ))

    # Async pattern
    story.append(Paragraph("1. Async Database Sessions", styles['Subsection']))
    story.append(Paragraph(
        "CRITICAL: Always use <font face='Courier'>async with get_session() as db:</font> context manager, "
        "NOT <font face='Courier'>Depends(get_session)</font> injection.",
        styles['CustomBody']
    ))

    async_example = """
# WRONG - will cause errors
async def my_route(db: AsyncSession = Depends(get_session)):
    result = await db.execute(...)  # ERROR!

# CORRECT - use context manager
async def my_route(request: Request):
    async with get_session() as db:
        result = await db.execute(...)  # Works!
        # All DB code must be inside this block
    """

    story.append(Paragraph(
        f"<font face='Courier' size='8'>{async_example}</font>",
        ParagraphStyle('example',
                      parent=styles['CustomCode'],
                      fontSize=8,
                      fontName='Courier',
                      leading=10)
    ))

    # Platform differences
    story.append(Paragraph("2. Platform API Differences", styles['Subsection']))
    diff_data = [
        ["Field", "Reverb", "eBay", "Shopify"],
        ["Quantity", "inventory", "QuantityAvailable", "inventoryLevel"],
        ["Status", "state (live/sold)", "ListingStatus", "status (active)"],
        ["Price", "price.amount", "StartPrice", "variants[0].price"],
    ]

    diff_table = Table(diff_data, colWidths=[1.2*inch, 1.3*inch, 1.5*inch, 1.5*inch])
    diff_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['accent']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(diff_table)

    story.append(Spacer(1, 0.1*inch))

    # Common gotchas
    story.append(Paragraph("3. Common Gotchas", styles['Subsection']))
    gotchas = [
        "Never use conda - always activate venv with <font face='Courier'>source venv/bin/activate</font>",
        "Check actual table schema before writing queries (column names change!)",
        "eBay XML has string booleans ('true'/'false') not Python bools",
        "Shopify GraphQL IDs require <font face='Courier'>gid://shopify/Product/123</font> format",
        "Reverb API rate limit is 120 req/min - implement exponential backoff",
        "V&R Selenium requires Chrome service running in Railway",
        "SKUs are case-insensitive - use LOWER() in SQL comparisons",
    ]
    for gotcha in gotchas:
        story.append(Paragraph(f"⚠ {gotcha}", styles['CustomBullet']))

    story.append(PageBreak())
    return story


def create_resources(styles):
    """Resources and references"""
    story = []

    story.append(Paragraph("Resources & Documentation", styles['SectionHeader']))

    # Internal docs
    story.append(Paragraph("Internal Documentation", styles['Subsection']))
    internal_docs = [
        ("docs/todo.md", "Current priorities and completed work"),
        ("docs/multi-tenant-roadmap.md", "Future SaaS architecture plan"),
        ("docs/TECH_STACK_AND_ONBOARDING.md", "Complete tech stack reference"),
        ("docs/dhl-integration.md", "DHL shipping integration details"),
        ("CLAUDE.md", "Critical reminders and patterns (for AI and humans!)"),
        ("docs/api/", "API endpoints and platform integration docs"),
    ]
    for doc, desc in internal_docs:
        story.append(Paragraph(
            f"<b>{doc}</b>: {desc}",
            styles['CustomBullet']
        ))

    story.append(Spacer(1, 0.1*inch))

    # External docs
    story.append(Paragraph("External Documentation", styles['Subsection']))
    external_docs = [
        ("FastAPI", "https://fastapi.tiangolo.com/async/"),
        ("SQLAlchemy 2.0", "https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html"),
        ("Reverb API", "https://reverb.com/page/api"),
        ("eBay Trading API", "https://developer.ebay.com/devzone/xml/docs/reference/ebay/"),
        ("Shopify GraphQL", "https://shopify.dev/api/admin-graphql"),
        ("Railway", "https://docs.railway.app/"),
    ]
    for name, url in external_docs:
        story.append(Paragraph(
            f"<b>{name}</b>: <font face='Courier' size='8'>{url}</font>",
            styles['CustomBullet']
        ))

    story.append(Spacer(1, 0.2*inch))

    # Contact
    story.append(Paragraph("Getting Help", styles['Subsection']))
    story.append(Paragraph(
        "For questions about the codebase, start by:",
        styles['CustomBody']
    ))
    help_steps = [
        "Reading the relevant docs/ file for context",
        "Searching the codebase for similar patterns",
        "Checking CLAUDE.md for known gotchas",
        "Running the code locally and adding debug prints",
        "Asking Tom or Codex",
    ]
    for step in help_steps:
        story.append(Paragraph(f"• {step}", styles['CustomBullet']))

    return story


def generate_pdf():
    """Main PDF generation function"""
    output_path = Path(__file__).parent.parent / "docs" / "RIFF_Developer_Onboarding.pdf"

    # Create PDF
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=1*inch,
        title="RIFF Developer Onboarding Pack",
        author="RIFF Development Team"
    )

    # Create styles
    styles = create_styles()

    # Build story
    story = []
    story.extend(create_cover_page(styles))
    story.extend(create_executive_summary(styles))
    story.extend(create_functions_section(styles))
    story.extend(create_highlevel_stack(styles))
    story.extend(create_detailed_stack(styles))
    story.extend(create_architecture_diagram(styles))
    story.extend(create_database_schema(styles))
    story.extend(create_getting_started(styles))
    story.extend(create_key_patterns(styles))
    story.extend(create_resources(styles))

    # Build PDF with custom canvas for page numbers
    doc.build(story, canvasmaker=NumberedCanvas)

    print(f"\n✓ PDF generated successfully: {output_path}")
    print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")
    return output_path


if __name__ == "__main__":
    generate_pdf()
