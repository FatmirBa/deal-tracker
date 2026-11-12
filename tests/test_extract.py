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
    assert parse_number("1 299,90") == 1299.9  # direct parse still accepts spaces
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


def test_title_digits_never_merge_into_price():
    # Bingo: model number right before the price
    assert find_prices("FINLUX FRIŽIDER GN 76L/10L 110/FN1101\n   349,00 KM") == [349.0]
    assert find_prices('Samsung TV 55 899 KM') == [899.0]
    assert find_prices("1\u00a0299,00 KM") == [1299.0]  # non-breaking space thousands still fine


def test_json_map_feed():
    """App-style shop: products come from a JSON feed; the sale price wins and the normal price becomes the 'was' price."""
    feed = ('{"items":[{"id":602,"name":"Ugaona garnitura Victoria Bli","price":2139,"discountedPrice":1604,"image":"https://api.test/i/602.jpg"},'
            '{"id":452,"name":"Ugaona garnitura Gloria","price":649,"discountedPrice":null,"image":"abc"},'
            '{"id":9,"name":"Bez cijene","price":0,"discountedPrice":null}],"totalItems":3}')
    sel = {"json": {"items": "items", "id": "id", "title": "name", "price": ["discountedPrice", "price"], "old_price": "price",
                    "image": "image", "url_template": "https://viva.test/products/{id}"}}
    prods, rep = extract(feed, "https://api.test/api/Products", sel)
    assert rep["used"] == "jsonmap" and len(prods) == 2
    assert (prods[0].price, prods[0].old_price, prods[0].url) == (1604.0, 2139.0, "https://viva.test/products/602")
    assert prods[0].image == "https://api.test/i/602.jpg"
    assert (prods[1].price, prods[1].old_price, prods[1].image) == (649.0, None, None)


def test_bigbang_cards_ignore_instalments():
    sel = {"card": "article.cp", "title": ".cp-title", "price": ".current-price",
           "old_price": "del.old-price", "link": "a.cp-product-link-overlay"}
    def card(i, name, cur, old=None):
        old_html = f'<del class="old-price">{old} KM</del>' if old else ""
        return (f'<article class="cp"><a class="cp-product-link-overlay" href="/{name}-p-{i}/"></a>'
                f'<div class="cp-title">Perilica rublja {name.split('-',1)[0].title()} {name.split('-',1)[1].upper().replace('-','')}</div>'
                f'<div class="cp-card-price-row"><div class="price cp-price"><div class="price-line">'
                f'<div class="current-price">{cur} KM</div>{old_html}</div></div></div>'
                f'<div>ili 26,25 KM / 24 rate</div></article>')
    html = "<html><body>" + card(1, "beko-bm3wfsu38213wpbb", "629,90", "839") \
        + card(2, "bosch-wan28163by", "845") + card(3, "gorenje-wnei84aps", "699") + "</body></html>"
    items, info = extract(html, "https://www.bigbang.ba", sel)
    by = {p.title.split()[-1]: p for p in items}
    assert len(items) == 3
    assert by["BM3WFSU38213WPBB"].price == 629.9 and by["BM3WFSU38213WPBB"].old_price == 839
    assert by["WAN28163BY"].price == 845 and not by["WAN28163BY"].old_price
    assert items[0].url == "https://www.bigbang.ba/beko-bm3wfsu38213wpbb-p-1/"
