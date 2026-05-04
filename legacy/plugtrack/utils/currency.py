from models.settings import Settings

def get_currency_symbol(user_id, default_currency='GBP'):
    """Get the currency symbol for a user"""
    currency = Settings.get_setting(user_id, 'currency', default_currency)
    
    currency_symbols = {
        'GBP': '£',
        'EUR': '€',
        'USD': '$'
    }
    
    return currency_symbols.get(currency, '£')

def format_currency(amount, user_id, default_currency='GBP', decimal_places=2):
    """Format a currency amount for display"""
    symbol = get_currency_symbol(user_id, default_currency)
    
    if amount is None:
        amount = 0.0
    
    formatted_amount = f"{float(amount):.{decimal_places}f}"
    return f"{symbol}{formatted_amount}"

def get_currency_info(user_id, default_currency='GBP'):
    """Get complete currency information for a user"""
    currency = Settings.get_setting(user_id, 'currency', default_currency)
    
    currency_info = {
        'GBP': {'symbol': '£', 'name': 'British Pound', 'code': 'GBP'},
        'EUR': {'symbol': '€', 'name': 'Euro', 'code': 'EUR'},
        'USD': {'symbol': '$', 'name': 'US Dollar', 'code': 'USD'}
    }
    
    return currency_info.get(currency, currency_info['GBP'])
