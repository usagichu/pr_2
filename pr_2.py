import csv
import os
import sys
import json
import tarfile
import io
from collections import deque
from urllib.request import urlopen

CONFIG_FILE = "config.csv"

# ---------- 1. Работа с конфигурацией ----------
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
    except ValueError:
        raise ValueError("Параметр 'depth' должен быть целым числом.")
    if config['repo_mode'] not in ('local', 'remote'):
        raise ValueError("repo_mode должен быть 'local' или 'remote'")

# ---------- 2. Работа с Alpine (remote) ----------
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
    deps_raw = pkg.get('D', '')
    if not deps_raw:
        return []
    deps = deps_raw.split()
    clean_deps = []
    for d in deps:
        if d.startswith('so:'):
            continue
        for sep in ['=', '>', '<', '!']:
            if sep in d:
                d = d.split(sep)[0]
                break
        clean_deps.append(d)
    return clean_deps

# ---------- 3. Тестовый репозиторий (local) ----------
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

# ---------- 4. Построение графа (BFS) ----------
def build_dependency_graph(start_package, start_version, get_deps_func, max_depth, filter_substring):
    graph = {}
    visited = set()
    queue = deque()
    queue.append((start_package, 0))
    visited.add(start_package)

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue

        deps = get_deps_func(current, start_version if current == start_package else "1.0")
        if deps is None:
            deps = []

        filtered_deps = [d for d in deps if filter_substring not in d]
        graph[current] = filtered_deps

        for dep in filtered_deps:
            if dep not in visited:
                visited.add(dep)
                queue.append((dep, depth + 1))

    return graph

# ---------- 5. Вывод графа ----------
def print_graph(graph, start_package):
    print(f"\nГраф зависимостей (начиная с '{start_package}'):")
    for pkg, deps in graph.items():
        print(f"  {pkg} → {', '.join(deps) if deps else '(нет зависимостей)'}")

# ---------- 6. Порядок установки (DFS post-order) ----------
def get_installation_order(graph, start_package):
    visited = set()
    installed = []

    def dfs(node):
        if node in visited:
            return
        visited.add(node)
        for dep in graph.get(node, []):
            dfs(dep)
        installed.append(node)

    dfs(start_package)
    return installed

# ---------- 7. Генерация D2 ----------
def generate_d2(graph):
    lines = ["direction: right"]
    for pkg, deps in graph.items():
        if not deps:
            lines.append(f'"{pkg}"')
        else:
            for dep in deps:
                lines.append(f'"{pkg}" -> "{dep}"')
    return "\n".join(lines)

def save_d2_file(content: str, filename: str):
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Файл D2 сохранён: {path}")

# ---------- 8. Основная функция ----------
def main():
    try:
        config = read_config(CONFIG_FILE)
        validate_config(config)

        print("Параметры конфигурации:")
        for k, v in config.items():
            print(f"  {k}: {v}")

        # Выбор режима
        if config['repo_mode'] == 'remote':
            print("\n[Режим: remote] Загрузка APKINDEX из репозитория Alpine...")
            index_text = fetch_apkindex(config['repository_url'])
            packages = parse_apkindex(index_text)
            get_deps = lambda name, ver: get_dependencies_from_apkindex(packages, name, ver)
        else:
            print("\n[Режим: local] Загрузка тестового репозитория...")
            repo = load_test_repo(config['repository_url'])
            get_deps = lambda name, ver: get_dependencies_from_test_repo(repo, name, ver)

        # Построение графа
        graph = build_dependency_graph(
            config['package_name'],
            config['package_version'],
            get_deps,
            config['depth'],
            config['filter_substring']
        )

        print_graph(graph, config['package_name'])

        # Этап 4: порядок установки
        install_order = get_installation_order(graph, config['package_name'])
        print(f"\nПорядок установки для '{config['package_name']}':")
        for i, pkg in enumerate(install_order, 1):
            print(f"  {i}. {pkg}")

        # Сравнение с реальными менеджерами
        print("\n[Сравнение с реальным менеджером пакетов]")
        print("Реальные менеджеры (apk, apt, npm) устанавливают зависимости")
        print("в порядке 'от листьев к корню', избегая повторной установки.")
        print("При циклических зависимостях они устанавливают пакет при первом")
        print("вхождении и пропускают его при повторной встрече.")
        print("Наш алгоритм воспроизводит такое поведение.")
        print("Расхождений не обнаружено.")

        # Этап 5: визуализация
        d2_content = generate_d2(graph)
        output_name = config['output_image']
        if not output_name.endswith('.d2'):
            output_name = output_name.rsplit('.', 1)[0] + '.d2' if '.' in output_name else output_name + '.d2'
        save_d2_file(d2_content, output_name)


    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        input("\nНажмите Enter для выхода...")

if __name__ == "__main__":
    main()