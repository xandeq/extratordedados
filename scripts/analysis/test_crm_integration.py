import sys
import os
import random
import time

sys.path.insert(0, 'project/backend')
from app import sync_lead_to_alexandrequeiroz

email = f"test_{int(time.time())}_{random.randint(100,999)}@extrator.com.br"
test_lead = {
    'email': email,
    'company_name': 'Company VPS Auth Test',
    'phone': '11999999999',
    'city': 'Vitoria',
    'state': 'ES',
    'source': 'test-script'
}

print(f"Testing insertion for: {email}")
success, message, customer_id = sync_lead_to_alexandrequeiroz(test_lead)

print(f"Success: {success}")
print(f"Message: {message}")
print(f"Customer ID: {customer_id}")
