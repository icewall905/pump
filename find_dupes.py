import re

# Open your web_player.py file
with open('web_player.py', 'r') as f:
    content = f.read()

# Find all route definitions
route_pattern = r'@app\.route\([\'"]([^\'"]+)[\'"]\)'
routes = re.findall(route_pattern, content)

# Find duplicates
duplicates = {}
for route in routes:
    if route in duplicates:
        duplicates[route] += 1
    else:
        duplicates[route] = 1

# Print duplicated routes
print("Duplicated routes:")
for route, count in duplicates.items():
    if count > 1:
        print(f"'{route}' appears {count} times")