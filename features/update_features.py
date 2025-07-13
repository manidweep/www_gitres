#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2025 The Evolution X Project
# SPDX-License-Identifier: Apache-2.0

import sys
import requests
import xml.etree.ElementTree as ET
import re
import json
import os

def print_error(msg):
    print(f"\033[91m{msg}\033[0m")

def clean_xml_comments(xml_text):
    return re.sub(r'', '', xml_text, flags=re.DOTALL)

def get_android_attr(element, attr):
    return element.get(f"{{http://schemas.android.com/apk/res/android}}{attr}")

def fetch_file_content(branch, filepath, token, repo="packages_apps_Evolver"):
    url = f"https://raw.githubusercontent.com/Evolution-X/{repo}/{branch}/{filepath}"
    headers = {"Authorization": f"token {token}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to fetch {filepath} from {repo}/{branch}: {e}")
        return None

def parse_strings_xml(xml_text):
    root = ET.fromstring(xml_text)
    return {elem.get('name'): elem.text or "" for elem in root.findall('string')}

def parse_preference_fragment_xml(xml_text):
    clean_text = clean_xml_comments(xml_text)
    root = ET.fromstring(clean_text)
    categories = []
    for category_elem in root.findall("PreferenceCategory"):
        prefs = []
        for pref_elem in category_elem:
            title_key = get_android_attr(pref_elem, "title")
            if title_key:
                prefs.append({
                    "key": get_android_attr(pref_elem, "key"),
                    "title_key": title_key,
                    "summary_key": get_android_attr(pref_elem, "summary")
                })
        categories.append({
            "title_key": get_android_attr(category_elem, "title"),
            "preferences": prefs
        })
    return categories

def resolve_string(ref, *string_dicts):
    if not ref or not ref.startswith("@string/"):
        return ref or ""

    key = ref.split("/", 1)[1]
    for d in string_dicts:
        if key in d:
            return d[key]
    return f"<MISSING {key}>"

def clean_display_text(text):
    if not text:
        return ""
    return text.split('\\n')[0].replace("\\'", "'")

def load_replacements():
    if os.path.exists("replacements.json"):
        try:
            with open("replacements.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print_error(f"Error loading replacements.json: {e}")
    return {}

def save_replacements(replacements):
    try:
        with open("replacements.json", "w", encoding="utf-8") as f:
            json.dump(replacements, f, indent=4, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print_error(f"Error saving replacements.json: {e}")

def scrape_features(branch, token, replacements):
    print(f"Scraping {branch}")

    main_xml_content = fetch_file_content(branch, "res/xml/evolution_settings.xml", token)
    if not main_xml_content:
        print_error(f"Skipping {branch}: evolution_settings.xml not found.")
        return

    main_root = ET.fromstring(clean_xml_comments(main_xml_content))

    main_preferences = []
    for pref_elem in main_root.findall("Preference"):
        main_preferences.append({
            "key": get_android_attr(pref_elem, "key"),
            "title_key": get_android_attr(pref_elem, "title"),
            "summary_key": get_android_attr(pref_elem, "summary")
        })

    if not main_preferences:
        print(f"No top-level preferences found in evolution_settings.xml for {branch}.")
        return

    strings_dict = {}
    fallback_strings = []

    evolver_strings = fetch_file_content(branch, "res/values/evolution_strings.xml", token)
    if evolver_strings:
        strings_dict = parse_strings_xml(evolver_strings)

    for repo_name, file_path in [
        ("packages_apps_Settings", "res/values/evolution_strings.xml"),
        ("packages_apps_Settings", "res/values/strings.xml"),
        ("packages_apps_Settings", "res/values/cm_strings.xml")
    ]:
        content = fetch_file_content(branch, file_path, token, repo=repo_name)
        if content:
            fallback_strings.append(parse_strings_xml(content))

    processed_categories_data = []
    for main_pref in main_preferences:
        key = main_pref["key"]
        if key == "about":
            continue

        title = clean_display_text(resolve_string(main_pref["title_key"], strings_dict, *fallback_strings))
        summary = clean_display_text(resolve_string(main_pref["summary_key"], strings_dict, *fallback_strings))

        fragment_xml_path = f"res/xml/evolution_settings_{key}.xml"
        fragment_content = fetch_file_content(branch, fragment_xml_path, token)

        sub_preferences_data = []
        if fragment_content:
            sub_preferences_data = parse_preference_fragment_xml(fragment_content)
        else:
            print_error(f"Missing fragment XML for '{key}' ({fragment_xml_path}) on {branch}.")

        processed_categories_data.append({
            "key": key,
            "title": title,
            "summary": summary,
            "sub_preferences": sub_preferences_data
        })

    output_data_for_branch = []
    for main_cat in processed_categories_data:
        main_cat_title = main_cat["title"]
        current_main_cat_entry = {
            main_cat_title: {
                "summary": main_cat["summary"]
            }
        }

        for sub_cat in main_cat["sub_preferences"]:
            sub_cat_title = clean_display_text(resolve_string(sub_cat['title_key'], strings_dict, *fallback_strings))
            sub_cat_features = {}

            for pref in sub_cat["preferences"]:
                pref_key = pref.get("key", "<no-key>")
                pref_title = clean_display_text(resolve_string(pref["title_key"], strings_dict, *fallback_strings))
                pref_summary = clean_display_text(resolve_string(pref["summary_key"], strings_dict, *fallback_strings))

                if re.search(r'%s', pref_summary) or not pref_summary:
                    if pref_key in replacements:
                        pref_summary = replacements[pref_key]
                    else:
                        print(f"Action needed for '{pref_title}' (Key: {pref_key}). Current summary: '{pref_summary}'")
                        new_summary = input("Enter replacement summary (leave empty to skip): ").strip()
                        if new_summary:
                            pref_summary = new_summary
                            replacements[pref_key] = new_summary
                        else:
                            pref_summary = " "

                sub_cat_features[pref_title] = pref_summary

            current_main_cat_entry[main_cat_title][sub_cat_title] = sub_cat_features

        output_data_for_branch.append(current_main_cat_entry)

    os.makedirs("branches", exist_ok=True)
    filename = os.path.join("branches", f"{branch}.json")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output_data_for_branch, f, indent=4, ensure_ascii=False)
            f.write("\n")
        print(f"Saved to {filename}")
    except Exception as e:
        print_error(f"Error saving {filename}: {e}")

def main():
    if len(sys.argv) != 2:
        print_error("Usage: python script.py <GITHUB_TOKEN>")
        sys.exit(1)

    github_token = sys.argv[1]

    try:
        response = requests.get(f"https://api.github.com/repos/Evolution-X/packages_apps_Evolver/branches", headers={"Authorization": f"token {github_token}"})
        response.raise_for_status()
        branches = [b['name'] for b in response.json()]
        print(f"Evolver branches found: {', '.join(branches)}")
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to fetch branches: {e}")
        sys.exit(1)

    replacements = load_replacements()

    for branch in branches:
        scrape_features(branch, github_token, replacements)

    save_replacements(replacements)
    print("Done scraping features")

if __name__ == "__main__":
    main()
