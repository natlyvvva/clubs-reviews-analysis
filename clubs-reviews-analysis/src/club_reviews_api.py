"""Отзывы Google Maps через SerpApi .

Установка: python3 -m pip install requests
Запуск: python3 club_reviews_api.py
Ключ: личный ключ SerpApi, вводится скрыто или через SERPAPI_API_KEY.
Документация: https://serpapi.com/google-maps-reviews-api
Выборка последних доступных отзывов НЕ является полной историей.
"""

import argparse
import csv
import getpass
import os
from datetime import datetime, timezone
from pathlib import Path

import requests


def api_get(api_key, **params):
    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={"api_key": api_key, **params},
            timeout=60,
        )
    except requests.RequestException:
        raise RuntimeError("Не удалось связаться с SerpApi. Проверьте сеть.") from None
    if response.status_code != 200:
        raise RuntimeError(
            f"SerpApi вернул HTTP {response.status_code}. "
            "Проверьте ключ, квоту и параметры в личном кабинете."
        )
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("SerpApi вернул ответ не в формате JSON.") from None
    if data.get("error"):
        message = str(data["error"]).replace(api_key, "[KEY]")
        raise RuntimeError(f"SerpApi: {message}")
    return data


def find_place(api_key, query):
    data = api_get(api_key, engine="google_maps", type="search", q=query, hl="ru")
    places = data.get("local_results") or []
    if not places and data.get("place_results"):
        places = [data["place_results"]]
    places = [p for p in places if p.get("data_id")]
    if not places:
        print(f"НЕ НАЙДЕНО: {query}")
        return None
    p = places[0]
    print(f"OK: {query}  ->  {p.get('title')} | {p.get('address')}")
    return p


def iter_reviews(api_key, place, pages):
    token = None
    seen_tokens, seen_reviews = set(), set()
    for page in range(1, pages + 1):
        params = dict(
            engine="google_maps_reviews", data_id=place["data_id"],
            hl="ru", sort_by="newestFirst",
        )
        if token:
            params.update(next_page_token=token, num=20)
        data = api_get(api_key, **params)
        reviews = data.get("reviews") or []
        print(f"Страница {page}: получено {len(reviews)} записей.")
        for review in reviews:
            key = review.get("review_id") or review.get("link")
            if key and key in seen_reviews:
                continue
            if key:
                seen_reviews.add(key)
            original = (review.get("extracted_snippet") or {}).get("original")
            yield {
                "club": place.get("title", ""),
                "address": place.get("address", ""),
                "data_id": place["data_id"],
                "review_id": review.get("review_id", ""),
                "rating": review.get("rating"),
                "date_iso": review.get("iso_date", ""),
                "edited_at": review.get("iso_date_of_last_edit", ""),
                "date_label": review.get("date", ""),
                "text": original or review.get("snippet", ""),
                "original_text_available": bool(original),
                "source": review.get("source", ""),
                "review_url": review.get("link", ""),
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "club_rating": place.get("rating"),
                "club_reviews_total": place.get("reviews"),
            }
        token = (data.get("serpapi_pagination") or {}).get("next_page_token")
        if not token or not reviews or token in seen_tokens:
            print("Следующая страница недоступна. Полнота истории не гарантируется.")
            return
        seen_tokens.add(token)
    print("Достигнут заданный лимит страниц; выгрузка может быть неполной.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=2, help="Лимит страниц отзывов")
    parser.add_argument("--clubs", default="clubs.txt")
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("--pages должен быть положительным")

    api_key = os.environ.get("SERPAPI_API_KEY", "").strip() or getpass.getpass(
        "Личный API-ключ SerpApi (ввод скрыт): "
    ).strip()
    if not api_key:
        raise RuntimeError("Нужен API-ключ из личного кабинета SerpApi.")

    queries = [l.strip() for l in open(args.clubs, encoding="utf-8") if l.strip()]
    print(f"Заведений в списке: {len(queries)}")

    path = Path("club_reviews_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".csv")
    count = 0
    try:
        with path.open("x", encoding="utf-8-sig", newline="") as output:
            writer = None
            for query in queries:
                place = find_place(api_key, query)
                if place is None:
                    continue
                for row in iter_reviews(api_key, place, args.pages):
                    if writer is None:
                        writer = csv.DictWriter(output, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    output.flush()
                    count += 1
    finally:
        print(f"Сохранено записей: {count}. Файл: {path.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
