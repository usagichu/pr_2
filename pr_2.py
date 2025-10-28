import csv
import os
import sys
import json
import tarfile
import io
from collections import deque
from urllib.request import urlopen
from urllib.error import URLError

CONFIG_FILE = "config.csv"

# ---------- Вспомогательные функции из Этапа 2 ----------
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

# ---------- Работа с Alpine (remote) ----------
def fetch_apkindex(url: str) -> str:
    index_url = url.rstrip('/') + '/APKINDEX.tar.gz'
    try:
        with urlopen(index_url, timeout=10) as response:
            data = response.read()
    except Exception as e:
        raise RuntimeError(f"Не удалось загрузить APKINDEX: {e}")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
            for member in tar.getmembers():
                if member.name == 'APKINDEX':
                    f = tar.extractfile(member)
                    if f:
                        return f.read().decode('utf-8')
            raise RuntimeError("APKINDEX не найден в архиве.")
    except Exception as e:
        raise RuntimeError(f"Ошибка распаковки: {e}")

def parse_apkindex(index_text: str):
    packages = []
    current = {}
    for line in index_text.splitlines():
        if not line.strip():
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

def get_dependencies_from_apkindex(packages, name, version):
    pkg = next((p for p in packages if p.get('P') == name and p.get('V') == version), None)
    if not pkg:
        return None
    deps = pkg.get('D', '').split() if pkg.get('D') else []
    # Убираем версионные условия: "lib>=1.0" → "lib"
    clean_deps = []
    for d in deps:
        if d.startswith('so:'):
            continue  # пропускаем системные зависимости (по желанию)
        # Удаляем всё после первого символа сравнения
        for sep in ['=', '>', '<', '!']:
            if sep in d:
                d = d.split(sep)[0]
                break
        clean_deps.append(d)
    return clean_deps

# ---------- Работа с тестовым репозиторием (local) ----------
def load_test_repo(path: str):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Тестовый репозиторий не найден: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_dependencies_from_test_repo(repo, name, version):
    pkg = repo.get(name)
    if not pkg or pkg.get('version') != version:
        return None
    return pkg.get('dependencies', [])

# ---------- Основная логика построения графа (BFS) ----------
def build_dependency_graph(
    start_package: str,
    start_version: str,
    get_deps_func,
    max_depth: int,
    filter_substring: str
):
    """
    Возвращает граф в виде словаря: {пакет: [зависимости]}
    """
    graph = {}
    visited = set()
    queue = deque()
    # Элемент: (package_name, depth)
    queue.append((start_package, 0))
    visited.add(start_package)

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue

        # Получаем зависимости
        deps = get_deps_func(current, start_version if current == start_package else "1.0")
        if deps is None:
            deps = []  # пакет не найден — считаем, что зависимостей нет

        # Фильтруем
        filtered_deps = [
            d for d in deps
            if filter_substring not in d
        ]

        graph[current] = filtered_deps

        # Добавляем в очередь новые узлы
        for dep in filtered_deps:
            if dep not in visited:
                visited.add(dep)
                queue.append((dep, depth + 1))

    return graph

# ---------- Вывод графа ----------
def print_graph(graph, start_package):
    print(f"\nГраф зависимостей (начиная с '{start_package}'):")
    for pkg, deps in graph.items():
        if deps:
            print(f"  {pkg} → {', '.join(deps)}")
        else:
            print(f"  {pkg} → (нет зависимостей)")

# ---------- Основная функция ----------
def main():
    try:
        config = read_config(CONFIG_FILE)
        validate_config(config)

        print("Параметры конфигурации:")
        for k, v in config.items():
            print(f"  {k}: {v}")

        # Выбираем функцию получения зависимостей
        if config['repo_mode'] == 'remote':
            print("\n[Режим: remote] Загрузка APKINDEX...")
            index_text = fetch_apkindex(config['repository_url'])
            packages = parse_apkindex(index_text)
            def get_deps(name, version):
                return get_dependencies_from_apkindex(packages, name, version)
            actual_version = config['package_version']

        elif config['repo_mode'] == 'local':
            print("\n[Режим: local] Загрузка тестового репозитория...")
            repo = load_test_repo(config['repository_url'])
            def get_deps(name, version):
                return get_dependencies_from_test_repo(repo, name, version)
            actual_version = config['package_version']

        else:
            raise ValueError("Неподдерживаемый режим")

        # Строим граф
        graph = build_dependency_graph(
            start_package=config['package_name'],
            start_version=actual_version,
            get_deps_func=get_deps,
            max_depth=config['depth'],
            filter_substring=config['filter_substring']
        )

        print_graph(graph, config['package_name'])

    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        if __name__ == "__main__":
            input("\nНажмите Enter для выхода...")
        sys.exit(1)

if __name__ == "__main__":
    main()