"""Registration syntax checks, kept consistent with the mobile form."""
import re


def is_valid_registration_email(email: str) -> bool:
    if len(email) > 254 or email.count('@') != 1:
        return False
    local, domain = email.split('@')
    if (not local or len(local) > 64 or local.startswith('.')
            or local.endswith('.') or '..' in local):
        return False
    if not re.fullmatch(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return False
    labels = domain.split('.')
    return (len(labels) >= 2
            and all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                    for label in labels)
            and re.fullmatch(r'[a-zA-Z]{2,63}', labels[-1]) is not None)


def registration_error(username: str, email: str, password: str):
    for value, label in ((username.strip(), 'username'), (email.strip(), 'email'),
                         (password, 'password')):
        if not value:
            return f'Please enter your {label}.'
    if not is_valid_registration_email(email.strip()):
        return 'Please enter a valid email address.'
    return None
