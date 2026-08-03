import requests

cookies = {'PHPSESSID': 'lk7gj9nue2r4fv4h3r5158j17p'}
headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'}

r = requests.get('https://fantasy.ekstraklasa.org/user-team/view/lubliniankakonskie', cookies=cookies, headers=headers)
print("status:", r.status_code)
print("final url:", r.url)
print("squad.push w tresci:", '$squad.push' in r.text)