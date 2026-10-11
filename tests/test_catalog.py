from wealth_advisor.catalog import compare_products, filter_products, load_catalog


def test_catalog_suitability_and_comparison_are_deterministic():
    products = load_catalog()
    suitable = filter_products(products, investor_class=2, amount=10_000)
    assert suitable
    assert all(product.risk_class <= 2 for product in suitable)
    first = compare_products(products, 10_000, 10, 2)
    second = compare_products(products, 10_000, 10, 2)
    assert [item.as_dict() for item in first] == [item.as_dict() for item in second]
    assert all(item.fee_drag >= 0 for item in first)


def test_catalog_filters_liquidity_and_exclusions():
    products = load_catalog()
    result = filter_products(products, 5, amount=10_000, liquidity_days=2, exclusions=["EQ-TECH"])
    assert all(item.liquidity_days <= 2 for item in result)
    assert "EQ-TECH" not in {item.id for item in result}

