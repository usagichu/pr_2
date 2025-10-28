import csv
import os

CONFIG_FILE = "config.csv"  # Имя файла по умолчанию

def read_config(config_path: str):
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Файл конфигурации не найден: {config_path}")

    with open(config_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)

    if len(rows) == 0:
        raise ValueError("Файл конфигурации пуст или не содержит данных.")
    if len(rows) > 1:
        raise ValueError("Файл конфигурации должен содержать только одну строку параметров.")

    return rows[0]

def validate_config(config: dict):
    required_keys = [
        'package_name',
        'repository_url',
        'repo_mode',
        'package_version',
        'output_image',
        'depth',
        'filter_substring'
    ]

    errors = []

    for key in required_keys:
        if key not in config or config[key] == '':
            errors.append(f"Отсутствует обязательный параметр: {key}")

    if errors:
        raise ValueError("Ошибки в конфигурации:\n" + "\n".join(errors))

    # Валидация depth
    try:
        depth = int(config['depth'])
        if depth < 0:
            errors.append("Параметр 'depth' должен быть неотрицательным целым числом.")
        else:
            config['depth'] = depth
    except ValueError:
        errors.append("Параметр 'depth' должен быть целым числом.")

    # Валидация repo_mode
    if config['repo_mode'] not in ('local', 'remote'):
        errors.append("Параметр 'repo_mode' должен быть 'local' или 'remote'.")

    if errors:
        raise ValueError("Ошибки в конфигурации:\n" + "\n".join(errors))

def main():
    try:
        config = read_config(CONFIG_FILE)
        validate_config(config)

        print("Загруженные параметры конфигурации:")
        for key, value in config.items():
            print(f"{key}: {value}")

    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        input("Нажмите Enter для выхода...")  # чтобы окно не закрывалось сразу в PyCharm
        exit(1)

if __name__ == "__main__":
    import sys
    main()