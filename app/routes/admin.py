from flask import Blueprint, render_template, session, redirect, url_for, flash, current_app

admin_bp = Blueprint('admin',
                     __name__,
                     template_folder='../templates', # Points to app/templates/
                                                     # So render_template('admin/file.html')
                     url_prefix='/admin')

@admin_bp.route('/services-status')
def services_status_page():
    if not session.get('is_admin', False): # Basic admin check
        current_app.logger.warning("Non-admin user tried to access /admin/services-status.")
        flash('You must be an administrator to view this page.', 'error')
        # Assuming 'routes.login' is the correct endpoint for your login page.
        # If your main blueprint is named 'main', it might be 'main.login' or similar.
        # Fallback to a generic home if login route is uncertain.
        login_route = current_app.config.get('LOGIN_ROUTE', 'routes.home')
        try:
            return redirect(url_for(login_route))
        except Exception: # Catch if route doesn't exist
             current_app.logger.error(f"Admin redirect route '{login_route}' not found. Redirecting to '/'.")
             return redirect(url_for('routes.home')) # Fallback to a known route

    return render_template('admin/services_status.html', title="Services Status")

# Note: The 'LOGIN_ROUTE' in app.config is hypothetical.
# You'd replace 'routes.login' or 'routes.home' with the actual endpoint name
# for your login page or main page if 'routes' is not the correct blueprint name.
# For example, if you have a blueprint `auth_bp = Blueprint('auth', ...)` with a login route,
# it would be `auth.login`. If it's on the main app (rare for login) or a 'main' blueprint, adjust accordingly.
# The current code assumes the main routes are on a blueprint named 'routes'.
# If there's a main blueprint like `main_bp = Blueprint('main', ...)` for non-admin pages,
# then the redirect might be `url_for('main.home_page_function_name')`.
# Using 'routes.home' as a placeholder.
# The session check `session.get('is_admin', False)` is standard.
# Ensure that your login mechanism correctly sets `session['is_admin'] = True` for admin users.
