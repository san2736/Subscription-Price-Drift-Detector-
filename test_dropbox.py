import requests
from bs4 import BeautifulSoup

html = requests.get("https://www.dropbox.com/plans", headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).text
soup = BeautifulSoup(html, 'html.parser')

for cell in soup.select('.dwg-plan-comparison-table__header-cell'):
    print(list(cell.stripped_strings))