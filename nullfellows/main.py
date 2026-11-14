import requests

BASE_URL = "https://www.nullfellows.com/"

def check_candidate(code):
    try:
        r = requests.get(
            BASE_URL + code,
            timeout=15,
            allow_redirects=True
        )

        if r.status_code == 404:
            return False

        if r.status_code == 200 and r.url.rstrip("/") != BASE_URL.rstrip("/"):
            print("\n" + "=" * 50)
            print("POTENTIAL SOLUTION:", code)
            print("URL:", r.url)
            print("CONTENT:")
            print(r.text[:3000])
            print("=" * 50)
            return True

        return False

    except requests.RequestException as e:
        print("Error:", e)
        return False