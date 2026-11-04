from tracker.extract import extract
from tracker.prices import find_prices, parse_number, model_code, norm

WOO = """<html><body><ul class="products columns-4">
""" + "".join(f"""<li class="product type-product post-{i}">
 <a href="/proizvod/gorenje-wnei84aps-{i}/" class="woocommerce-LoopProduct-link"><img data-src="/img/{i}.jpg" alt="x">
 <h2 class="woocommerce-loop-product__title">Gorenje veš mašina WNEI84APS {i}kg</h2></a>
 <span class="price"><del><span class="amount">{899+i},00 KM</span></del> <ins><span class="amount">{699+i},00 KM</span></ins></span>
 <div class="rate">Na 12 rata: 58,25 KM mjesečno</div>
 <a href="?add-to-cart={i}" class="button">Dodaj u korpu</a></li>""" for i in range(6)) + "</ul></body></html>"

LD = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
{"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Beko mašina za suđe DVN05320W","url":"https://shop.ba/p/1","offers":{"@type":"Offer","price":"549.00","priceCurrency":"BAM"}}},
{"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Bosch SMS2ITW08E Serie 2","url":"https://shop.ba/p/2","offers":{"@type":"Offer","price":"799.00","priceCurrency":"BAM"}}}]}</script></head><body></body></html>"""

NEXT = """<html><body><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"data":[
{"id":101,"title":"Samsung TV 55\\" UE55DU7172","price":"899 KM","slug":"artikal/101","images":["https://img/1.jpg"]},
{"id":102,"title":"LG OLED55B42LA televizor","price":1999,"slug":"artikal/102"},
{"id":103,"title":"Hisense 50A6K 4K Smart","price":{"amount":649},"slug":"artikal/103"}]}}}</script></body></html>"""

OLXAPI = '{"data":[{"id":5551,"title":"Ugaona garnitura na razvlačenje","price":450,"display_price":"450 KM"},{"id":5552,"title":"Ugaona garnitura siva","price":0,"display_price":"Po dogovoru"}]}'

def test_parse():
    assert parse_number("1.299,00") == 1299.0
    assert parse_number("1 299,90") == 1299.9
    assert parse_number("1,299.00") == 1299.0
    assert parse_number("849,9") == 849.9
    assert find_prices("Cijena: 1.299,00 KM, rata 108,25 KM mjesečno") == [1299.0]
    assert find_prices("KM 549,00") == [549.0]
    assert model_code("Gorenje veš mašina WNEI84APS 8kg 1400 obrtaja") == "WNEI84APS"
    assert model_code('Samsung TV 55" UE55DU7172UXXH') == "UE55DU7172UXXH"
    assert norm("Mašina za Suđe ĐAK") == "masina za sude dak"

def test_woo_cards():
    prods, rep = extract(WOO, "https://domod.ba/pretraga?q=x")
    assert rep["used"] == "cards", rep
    assert len(prods) == 6
    p = prods[0]
    assert p.price == 699.0 and p.old_price == 899.0, p
    assert p.url == "https://domod.ba/proizvod/gorenje-wnei84aps-0/"
    assert "WNEI84APS" in p.title and p.image.endswith("/img/0.jpg")

def test_jsonld():
    prods, rep = extract(LD, "https://shop.ba/")
    assert rep["used"] in ("jsonld", "embedded") and len(prods) == 2
    assert prods[0].price == 549.0

def test_next():
    prods, rep = extract(NEXT, "https://olx.ba/pretraga")
    assert rep["used"] == "embedded" and len(prods) == 3, rep
    assert {p.price for p in prods} == {899.0, 1999.0, 649.0}
    assert prods[0].url == "https://olx.ba/artikal/101"

def test_json_api_template():
    prods, rep = extract(OLXAPI, "https://olx.ba/api/search", url_template="https://olx.ba/artikal/{id}")
    assert len(prods) == 1 and prods[0].url == "https://olx.ba/artikal/5551" and prods[0].price == 450

def test_selectors():
    sel = {"card": "li.product", "title": "h2", "price": "ins .amount", "old_price": "del .amount"}
    prods, rep = extract(WOO, "https://domod.ba/", selectors=sel)
    assert rep["used"] == "selectors" and prods[2].price == 701.0 and prods[2].old_price == 901.0


def test_real_shop_formats():
    # Tehnodepo: English separators and a savings line
    assert find_prices("1,417.00 KM\n   1,133.60 KM\n  Ušteda: 283.40 KM") == [1417.0, 1133.6]
    # Topizbor: savings word separated from the amount by HTML indentation
    assert find_prices("871,00\n                KM\n   Ušteda\n                        196,00 KM\n   675,00\n      KM") == [871.0, 675.0]
    # Technoshop: ",-" prices
    assert find_prices("2.079,- KM 1.999,- KM") == [2079.0, 1999.0]
    # savings badge
    assert find_prices("892 KM -251 KM 641 KM") == [892.0, 641.0]
