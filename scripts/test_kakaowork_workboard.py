import datetime

from modules.kakaowork_notifier import post_contract_summary


class DummyItem:
    def __init__(self, model_name: str, quantity: int):
        self.model_name = model_name
        self.quantity = quantity


class DummyContract:
    def __init__(self, name: str, contract_date: str, delivery_due_date: str, items):
        self.contract_name = name
        self.contract_date = datetime.datetime.strptime(contract_date, "%Y-%m-%d").date()
        self.delivery_due_date = datetime.datetime.strptime(delivery_due_date, "%Y-%m-%d").date()
        self.items = items


class DummyProject:
    def __init__(self, project_id: int, temp_name: str, short_name: str):
        self.id = project_id
        self.temp_name = temp_name
        self.short_name = short_name


def main():
    project = DummyProject(project_id=99999, temp_name="테스트현장(자동발행)", short_name="테스트")
    contracts = [
        DummyContract(
            name="테스트 계약 A",
            contract_date="2026-03-06",
            delivery_due_date="2026-03-31",
            items=[
                DummyItem("LS-1000", 12),
                DummyItem("LS-2000", 8),
            ],
        )
    ]

    ok, message, data = post_contract_summary(project, contracts)
    print(f"[{'PASS' if ok else 'FAIL'}] {message}")
    if data:
        print(data)


if __name__ == "__main__":
    main()
