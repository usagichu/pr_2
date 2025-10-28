import csv
import os
import sys
import tarfile
import io
from urllib.request import urlopen
from urllib.error import URLError

CONFIG_FILE = "config.csv"

def read_config(config_path: str):
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Файл конфигурации не найден: {config_path}")

    with open(config_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)

    if len(rows) == 0:
        raise ValueError("Файл конфигурации пуст.")
    if len(rows) > 1:
        raise ValueError("Файл конфигурации должен содержать одну строку.")

    return rows[0]

def validate_config(config: dict):
    required = ['package_name', 'repository_url', 'repo_mode', 'package_version',
                'output_image', 'depth', 'filter_substring']
    for key in required:
        if key not in config or not config[key].strip():
            raise ValueError(f"Отсутствует параметр: {key}")

    # depth → int
    try:
        config['depth'] = int(config['depth'])
        if config['depth'] < 0:
            raise ValueError("Глубина должна быть >= 0")
    except ValueError as e:
        if "Глубина" not in str(e):
            raise ValueError("Параметр 'depth' должен быть целым числом.")
        else:
            raise

    if config['repo_mode'] not in ('local', 'remote'):
        raise ValueError("repo_mode должен быть 'local' или 'remote'")

def fetch_apkindex(url: str) -> str:
    """Скачивает и распаковывает APKINDEX.tar.gz, возвращает содержимое APKINDEX."""
    index_url = url.rstrip('/') + '/APKINDEX.tar.gz'
    try:
        with urlopen(index_url, timeout=10) as response:
            if response.getcode() != 200:
                raise URLError(f"HTTP {response.getcode()}")
            data = response.read()
    except Exception as e:
        raise RuntimeError(f"Не удалось загрузить APKINDEX по адресу {index_url}: {e}")

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
            # Ищем файл APKINDEX
            for member in tar.getmembers():
                if member.name == 'APKINDEX':
                    f = tar.extractfile(member)
                    if f:
                        return f.read().decode('utf-8')
            raise RuntimeError("Файл APKINDEX не найден в архиве.")
    except Exception as e:
        raise RuntimeError(f"Ошибка при распаковке APKINDEX.tar.gz: {e}")

def parse_apkindex(index_text: str):
    """Парсит APKINDEX и возвращает список пакетов в виде словарей."""
    packages = []
    current = {}
    for line in index_text.splitlines():
        if line.strip() == "":
            if current:
                packages.append(current)
                current = {}
            continue
        if ':' in line:
            key, value = line.split(':', 1)
            current[key] = value.strip()
    if current:
        packages.append(current)
    return packages

def find_package(packages, name, version):
    """Ищет пакет по имени и версии."""
    for pkg in packages:
        if pkg.get('P') == name and pkg.get('V') == version:
            return pkg
    return None

def main():
    try:
        config = read_config(CONFIG_FILE)
        validate_config(config)

        print("Загруженные параметры конфигурации:")
        for k, v in config.items():
            print(f"{k}: {v}")

        # Этап 2: сбор данных (только если repo_mode == 'remote')
        if config['repo_mode'] != 'remote':
            print("\nРежим не 'remote' — пропуск сбора данных.")
            return

        print("\n[Этап 2] Загрузка APKINDEX...")
        index_text = fetch_apkindex(config['repository_url'])
        print("APKINDEX загружен и распакован.")

        packages = parse_apkindex(index_text)
        print(f"Всего пакетов в индексе: {len(packages)}")

        target = find_package(packages, config['package_name'], config['package_version'])
        if not target:
            print(f"Пакет '{config['package_name']}' версии '{config['package_version']}' не найден.")
            return

        deps_str = target.get('D', '')
        if deps_str:
            dependencies = deps_str.split()
        else:
            dependencies = []

        print(f"\nПрямые зависимости пакета '{config['package_name']}' версии '{config['package_version']}':")
        if dependencies:
            for dep in dependencies:
                print(f"  - {dep}")
        else:
            print("  (отсутствуют)")

    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        if __name__ == "__main__":
            input("\nНажмите Enter для выхода...")
        sys.exit(1)

if __name__ == "__main__":
    main()