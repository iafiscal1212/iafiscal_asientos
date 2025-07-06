# This __init__.py file makes the 'config' directory a Python package.

# You can expose specific configurations or helper functions if needed.
# For example, to make `current_config` easily accessible:
# from .settings import current_config, DevelopmentConfig, ProductionConfig, TestingConfig

# Or a function to get the config:
# from .settings import get_config
# current_config = get_config()

# This allows imports like:
# from config import current_config
# or
# from config.settings import current_config (which is more explicit and often preferred)

# For now, just making it a package is sufficient.
# The settings module will be imported directly by other parts of the application.
print("config package loaded") # Optional: for debugging imports
