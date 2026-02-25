from datetime import datetime
from fastapi.templating import Jinja2Templates

# Initialize templates once
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["now"] = datetime.utcnow