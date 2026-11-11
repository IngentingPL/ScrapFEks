import os
import sys

import requests

# Cookie sesji czytamy ze zmiennej środowiskowej — nie wpisujemy go do repo.
cookie = os.environ.get("FANTASY_SESSION_COOKIE", "").strip()
if not cookie:
    print("Brak zmiennej środowiskowej FANTASY_SESSION_COOKIE.")
    print("Ustaw ją przed uruchomieniem, np.:")
    print("  export FANTASY_SESSION_COOKIE='...'")
    sys.exit(1)

cookies = {'PHPSESSID': cookie}
headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'}

r = requests.get('https://fantasy.ekstraklasa.org/user-team/view/lubliniankakonskie', cookies=cookies, headers=headers)
print("status:", r.status_code)
print("final url:", r.url)
print("squad.push w tresci:", '$squad.push' in r.text)
