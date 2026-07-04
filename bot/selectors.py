"""Trendyol CSS seçicileri — site güncellenirse burayı düzenleyin."""

SELECTORS = {
    # Genel
    "search_input": (
        'input[data-testid="suggestion"], '
        'input#suggestion, '
        '.search-box-container input[type="text"]:not(#vendor-search-handler), '
        'header input[type="search"]:not(#vendor-search-handler)'
    ),
    "search_button": 'button[type="submit"], .search-box-button',
    "cookie_accept": (
        "#onetrust-accept-btn-handler, "
        "button[id*='accept'], "
        "button:has-text('Tüm Tanımlama Bilgilerini Kabul Et'), "
        "button:has-text('Tümünü Kabul Et')"
    ),
    "app_banner_close": ".modal-close, .close-modal, button[aria-label='Kapat'], .overlay-close",
    "popup_close": ".modal-close, .fancybox-close, .close",
    # Arama / liste
    "product_link": (
        "a.product-card[href*='-p-'], "
        "div.p-card-wrppr a[href*='-p-'], "
        "[data-testid='product-card'] a[href*='-p-'], "
        "a[href*='-p-'][class*='product-card']"
    ),
    "product_card": "a.product-card, div.p-card-wrppr, [data-testid='product-card']",
    # Ürün detay
    "product_title": (
        "h1, h1 span, h1.product-name, "
        "[data-testid='product-name'], [data-testid='product-title']"
    ),
    "product_price": ".prc-dsc, .prc-slg",
    "add_to_cart": (
        "button[data-testid='add-to-cart-button'], "
        "button.add-to-basket, button[data-testid='add-to-basket'], "
        "button.add-to-cart-button"
    ),
    "favorite_btn": (
        "[data-testid='favorite-toggle']:not([aria-pressed='true']), "
        "button[data-testid='favorite-button']:not([aria-pressed='true']), "
        ".favourite-btn:not(.active), "
        "i.icon-heart:not(.icon-heart-filled), "
        "[class*='favorite-button']:not([aria-pressed='true'])"
    ),
    "favorite_active": (
        "[data-testid='favorite-toggle'][aria-pressed='true'], "
        "button[data-testid='favorite-button'][aria-pressed='true'], "
        ".favourite-btn.active, "
        "i.icon-heart-filled, "
        "[class*='favorite-button'][aria-pressed='true']"
    ),
    "size_option": ".sp-itm:not(.disabled), .size-box:not(.disabled)",
    "size_confirm": "button.add-to-basket, .add-to-basket-text",
    # Galeri
    "gallery_image": ".product-image-gallery img, .gallery-modal img, ._carousel img",
    "gallery_next": ".gallery-next, button[aria-label='Sonraki']",
    # Yorumlar
    "reviews_tab": "a[href*='yorum'], button:has-text('Değerlendirme'), button:has-text('Yorum')",
    "review_item": ".comment, .review-item, [class*='comment-list'] > div",
    "review_helpful": "button:has-text('Faydalı'), .helpful-button",
    # Mağaza
    "seller_link": "a[href*='magaza'], a.seller-name, .merchant-name a",
    "seller_follow": (
        "button[data-testid='follow'], "
        "button:has-text('Takip Et'), "
        "button:has-text('TAKİP ET'), "
        "button:has-text('Takip'), "
        ".follow-seller-btn, "
        "[class*='follow']:has-text('Takip')"
    ),
    # Koleksiyon / kupon
    "collection_btn": "button:has-text('Koleksiyona'), .collection-btn",
    "coupon_btn": "button:has-text('Kupon'), .coupon-collect",
    # Soru cevap
    "qa_tab": (
        "a:has-text('Soru ve Cevap'), button:has-text('Soru ve Cevap'), "
        "a:has-text('Soru'), button:has-text('Soru'), "
        "a:has-text('Satıcı Soruları'), button:has-text('Satıcı Soruları')"
    ),
    "qa_item": ".question-item, [class*='question']",
    "qa_input": "textarea[placeholder*='Soru'], textarea[name*='question'], #question-text",
    "qa_submit": "button:has-text('Gönder'), button:has-text('Sor'), button[type='submit']",
}
