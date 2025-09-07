from flask import Blueprint, render_template
from flask_login import login_required

help_bp = Blueprint('help', __name__, url_prefix='/help')

@help_bp.route('/')
@login_required
def index():
    """Help page with FAQs and documentation."""
    return render_template('help/index.html', title='Help & FAQ')
