"""Builds docs/EpiProt-yol-haritasi.pdf: a short slide deck (16:9) of what must be done before EpiProt is used for real.

python docs/make_roadmap_pdf.py   (needs reportlab; fonts: Segoe UI from Windows, or DejaVu Sans)
"""
import os
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

W, H = 960, 540
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'EpiProt-yol-haritasi.pdf')

TEAL, TEAL_D, TEAL_S = HexColor('#0E7C86'), HexColor('#075E66'), HexColor('#DDF1F1')
MINT, MINT_S = HexColor('#2E9E6B'), HexColor('#DFF3E8')
CORAL, CORAL_S = HexColor('#D9483B'), HexColor('#FBE3E0')
AMBER, AMBER_S = HexColor('#C77700'), HexColor('#FFF0D6')
INK, INK_S, BG, LINE = HexColor('#1B2B2E'), HexColor('#5B6B6E'), HexColor('#F4F8F8'), HexColor('#E3EAEA')
PURPLE, PURPLE_S = HexColor('#6B4FA0'), HexColor('#ECE6F6')

for name, files in (('R', ['C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']),
                    ('B', ['C:/Windows/Fonts/segoeuib.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'])):
    pdfmetrics.registerFont(TTFont(name, next(f for f in files if os.path.exists(f))))

c = canvas.Canvas(OUT, pagesize=(W, H))
c.setTitle('EpiProt – Gerçek kullanıma geçiş yol haritası')
c.setAuthor('EpiProt proje ekibi')
page = [0]
TOTAL = 10


def wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if pdfmetrics.stringWidth(t, font, size) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def text(x, y, s, font='R', size=16, color=INK, width=None, leading=None):
    """Draws (wrapped) text from the top line at y downwards; returns the y below the last line."""
    c.setFillColor(color)
    c.setFont(font, size)
    leading = leading or size * 1.3
    for line in (wrap(s, font, size, width) if width else [s]):
        c.drawString(x, y, line)
        y -= leading
    return y


def card(x, y, w, h, fill=white, r=18):
    c.setFillColor(fill)
    c.setStrokeColor(fill)
    c.roundRect(x, y, w, h, r, fill=1, stroke=0)


def dot(x, y, r, fill, label=None, size=16):
    c.setFillColor(fill)
    c.circle(x, y, r, fill=1, stroke=0)
    if label:
        c.setFillColor(white)
        c.setFont('B', size)
        c.drawCentredString(x, y - size * 0.35, label)


def pill(x, y, s, fg, bg, size=11):
    w = pdfmetrics.stringWidth(s, 'B', size) + 18
    card(x, y - 6, w, size + 12, bg, r=(size + 12) / 2)
    text(x + 9, y, s, 'B', size, fg)
    return w


def slide(title, kicker=None, color=TEAL):
    if page[0]:
        c.showPage()
    page[0] += 1
    c.setFillColor(BG)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(color)
    c.rect(0, H - 8, W, 8, fill=1, stroke=0)
    if kicker:
        text(48, H - 52, kicker.upper(), 'B', 12, color)
    text(48, H - 88, title, 'B', 30, INK)
    text(48, 24, 'EpiProt · gerçek kullanıma geçiş', 'R', 10, INK_S)
    c.setFont('R', 10)
    c.drawRightString(W - 48, 24, f'{page[0]} / {TOTAL}')


def priority_legend(y=24):
    x = 330
    for label, col in (('olmadan başlanamaz', CORAL), ('yayından önce', AMBER), ('kısa sürede', MINT)):
        dot(x, y + 4, 5, col)
        text(x + 10, y, label, 'R', 10, INK_S)
        x += pdfmetrics.stringWidth(label, 'R', 10) + 36


def item_rows(x, y, w, rows, gap=20):
    """rows: (priority color, what, why)"""
    for col, what, why in rows:
        dot(x + 8, y - 6, 7, col)
        y2 = text(x + 26, y, what, 'B', 15, INK, w - 26)
        y = text(x + 26, y2 + 2, why, 'R', 12.5, INK_S, w - 26, 16) - gap
    return y


# ------------------------------------------------------------------ 1. title
page[0] = 1
c.setFillColor(TEAL_D)
c.rect(0, 0, W, H, fill=1, stroke=0)
c.setFillColor(TEAL)
c.circle(W - 120, H - 60, 260, fill=1, stroke=0)
c.setFillColor(MINT)
c.circle(W - 60, 40, 120, fill=1, stroke=0)
text(64, H - 120, 'EPIPROT', 'B', 16, TEAL_S)
text(64, H - 190, 'Gerçek kullanıma geçiş', 'B', 46, white)
text(64, H - 245, 'yol haritası', 'B', 46, white)
text(64, H - 300, 'Gizlilik, onay ve yayın öncesi yapılacaklar', 'R', 20, TEAL_S)
text(64, 70, 'Kasım 2026 · Taslak – hukuki görüş değildir', 'R', 13, TEAL_S)

# ------------------------------------------------------------------ 2. ready today
slide('Uygulamada bugün hazır olan', 'Neredeyiz')
tiles = [
    (TEAL, 'Ülkeye göre metinler', 'Türkiye · AB · ABD, Türkçe ve İngilizce'),
    (MINT, '4 ayrı onay', 'Her biri kendi ekranında; evet ve hayırın sonucu yazılı'),
    (PURPLE, 'Gizlilik Merkezi', 'Onayı değiştir, geçmişi gör, veriyi indir veya sil'),
    (CORAL, 'Şifreli veri', 'Veritabanı ve kişisel bilgiler AES-256 ile şifreli'),
    (AMBER, 'Uygulama kilidi', 'Geçmiş ve Ayarlar parmak izi / ekran kilidiyle açılır'),
    (TEAL_D, 'Saat de onaya uyar', 'Onay yoksa saat sensörleri hiç açılmaz'),
]
for i, (col, t, s) in enumerate(tiles):
    x = 48 + (i % 3) * 292
    y = 300 - (i // 3) * 150
    card(x, y, 276, 130)
    dot(x + 34, y + 92, 16, col)
    text(x + 62, y + 86, t, 'B', 17, INK)
    text(x + 22, y + 52, s, 'R', 13, INK_S, 236, 17)
text(48, 92, 'Çocuklar için sade anlatım, 18 yaş hatırlatması, bakıcı onayı ve bakıcıya bilgi SMS’i de hazır.', 'R', 13, INK_S)

# ------------------------------------------------------------------ 3. five areas
slide('Gerçek kullanım için 5 alanda iş var', 'Büyük resim')
areas = [
    (TEAL, '1', 'Hukuk ve belgeler', 'Veri sorumlusu, hukukçu kontrolü, risk değerlendirmesi'),
    (CORAL, '2', 'Tıbbi cihaz', 'Nöbet algılayan yazılım tıbbi cihazdır: CE / TİTCK'),
    (PURPLE, '3', 'Klinik doğrulama', 'Gerçek cihazla ilk çalışma, etik kurul onayı'),
    (AMBER, '4', 'Google Play', 'SMS izni beyanı, sağlık beyanı, imza anahtarı'),
    (MINT, '5', 'Ülkeye özel', 'AB dilleri ve temsilci, ABD avukatı ve COPPA'),
]
for i, (col, n, t, s) in enumerate(areas):
    x = 48 + i * 176
    card(x, 180, 164, 210)
    dot(x + 82, 330, 30, col, n, 26)
    yy = text(x + 14, 270, t, 'B', 16, INK, 140)
    text(x + 14, yy - 4, s, 'R', 12.5, INK_S, 140, 16)
text(48, 140, 'En büyük ve en uzun iş: tıbbi cihaz süreci. En acil iş: veri sorumlusunu belirlemek ve metinleri hukukçuya kontrol ettirmek.',
     'B', 13, TEAL_D, 860)

# ------------------------------------------------------------------ 4. law
slide('Hukuk ve gizlilik belgeleri', 'Alan 1', TEAL)
item_rows(48, 392, 520, [
    (CORAL, 'Veri sorumlusunu belirle, metinlere yaz', 'Aydınlatma metninde kimliği zorunlu (KVKK m.10, GDPR m.13). Şu an boş.'),
    (CORAL, 'Metinleri Türk hukukçuya kontrol ettir', 'Hatalı rıza geçersizdir; o zaman veri işlemek hukuka aykırı olur.'),
    (AMBER, 'Risk değerlendirmesi (DPIA) ve VERBİS', 'Sağlık verisi için beklenen belge; sorun çıkarsa önlemin kanıtı.'),
    (AMBER, 'Web’de gizlilik politikası', 'Google Play sağlık uygulamalarında zorunlu tutuyor.'),
    (MINT, 'İhlal planı ve başvuru kanalı', 'İhlal 72 saatte bildirilir; başvuru 30 gün / 1 ayda cevaplanır.'),
])
card(610, 150, 302, 270, TEAL_S)
text(632, 388, 'Neden önemli?', 'B', 18, TEAL_D)
text(632, 356, 'Sağlık verisi kanunda “özel nitelikli” veri. Açık rıza ve doğru aydınlatma olmadan işlenemez.', 'R', 14, INK, 262, 19)
text(632, 250, 'Uygulama hazır; eksik olan, metinlerin bir uzman tarafından onaylanması ve imzalayacak kişinin belli olması.', 'R', 14, INK, 262, 19)
priority_legend()

# ------------------------------------------------------------------ 5. medical device
slide('Tıbbi cihaz mevzuatı', 'Alan 2 · en büyük iş', CORAL)
card(48, 300, 864, 110, CORAL_S)
text(72, 374, 'Nöbet algılayıp alarm veren yazılım tıbbi amaçlıdır → tıbbi cihaz sayılır', 'B', 19, CORAL)
text(72, 342, 'AB MDR Kural 11’e göre büyük olasılıkla en az sınıf IIa. Onaysız ürün tıbbi cihaz gibi sunulamaz;', 'R', 14, INK)
text(72, 322, 'o zamana kadar EpiProt “araştırma prototipi” olarak kalmalı (uygulamada yazıyor).', 'R', 14, INK)
steps = [('1', 'Sınıfı belirle', 'TİTCK ve AB MDR'), ('2', 'Süreçleri kur', 'ISO 13485 · IEC 62304\nISO 14971 · IEC 62366'),
         ('3', 'Onaylı kuruluş', 'CE işareti denetimi'), ('4', 'ABD için FDA', '510(k) – benzer ürünler\nbu yoldan onaylandı')]
for i, (n, t, s) in enumerate(steps):
    x = 48 + i * 220
    card(x, 130, 204, 140)
    dot(x + 36, 230, 18, CORAL, n, 18)
    text(x + 64, 224, t, 'B', 16, INK)
    yy = 190
    for line in s.split('\n'):
        yy = text(x + 22, yy, line, 'R', 13, INK_S)
    if i < 3:
        c.setFillColor(LINE)
        c.rect(x + 204, 178, 16, 4, fill=1, stroke=0)

# ------------------------------------------------------------------ 6. clinical
slide('Klinik doğrulama ve etik', 'Alan 3', PURPLE)
card(48, 290, 400, 130, PURPLE_S)
text(70, 388, 'Model gerçek cihazla hiç denenmedi', 'B', 19, PURPLE)
text(70, 356, 'Hastane verisiyle (SeizeIT2) ve simüle edilmiş saat nabzıyla eğitildi: 55 nöbetten 54, günde 0,24 yanlış alarm.',
     'R', 14, INK, 360, 19)
card(48, 170, 400, 100)
text(70, 238, 'Gerçek hayatta farklı çıkabilir', 'B', 16, INK)
text(70, 210, 'Bu yüzden gerçek EpiProt kafa bandı ve saatle ölçülmeli: kaçırılan nöbet, yanlış alarm, gecikme.', 'R', 14, INK_S, 360, 19)
item_rows(490, 392, 420, [
    (CORAL, 'Pilot çalışma planı', 'Kaç gönüllü, ne kadar süre, neyi ölçeceğiz.'),
    (CORAL, 'Etik kurul onayı + onam formları', 'İnsanlarla sağlık araştırması onaysız yapılamaz. Formlar uygulamadaki onaylardan ayrıdır.'),
    (AMBER, 'TİTCK ile klinik araştırma izni', 'Tıbbi cihazla yapılan araştırma ayrıca izne tabi olabilir.'),
    (AMBER, 'Yanlış nabız senaryosu', 'Nabzın gelmemesi çözüldü; hatalı değer gelmesi henüz test edilmedi.'),
])
priority_legend()

# ------------------------------------------------------------------ 7. play
slide('Google Play ve teknik yayın', 'Alan 4', AMBER)
item_rows(48, 392, 520, [
    (CORAL, 'SMS izni beyanı', 'SMS göndermek kısıtlı bir izin. “Acil durum” istisnasıyla başvurulur; reddedilirse telefonun kendi SMS uygulamasına geçilir.'),
    (CORAL, 'Data safety formu ve sağlık beyanı', 'Sağlık verisi işleyen uygulamalar için zorunlu.'),
    (CORAL, 'Yayın imza anahtarı', 'Telefon ve saat aynı anahtarla imzalanmazsa birbirini bulamaz; kaybolursa güncelleme yapılamaz.'),
    (CORAL, 'Kafa bandı Bluetooth bağlantısı', 'Donanım hazır olunca veri formatı netleşmeli; şimdilik kayıtlı veriyle çalışıyor.'),
    (AMBER, 'Bağımsız güvenlik incelemesi', 'Kod incelemesi ve sızma testi.'),
])
card(610, 150, 302, 270, AMBER_S)
text(632, 388, 'İpucu', 'B', 18, AMBER)
text(632, 356, 'SMS beyanı en belirsiz adım. Başvuruyu erken yapmak, red gelirse plan B’yi (SMS uygulamasıyla gönderme) zamanında hazırlamayı sağlar.',
     'R', 14, INK, 262, 19)
priority_legend()

# ------------------------------------------------------------------ 8. countries
slide('Ülkeye özel işler', 'Alan 5', MINT)
cols = [
    ('Türkiye', TEAL, ['Hukukçu kontrolü (KVKK)', 'VERBİS değerlendirmesi', 'TİTCK süreçleri']),
    ('Avrupa Birliği', PURPLE, ['Ülke dillerine profesyonel çeviri', 'AB temsilcisi (GDPR m.27)', 'CE işareti (MDR)']),
    ('ABD', CORAL, ['ABD’li avukat kontrolü', 'COPPA: FTC onaylı veli doğrulama', 'Washington için sağlık verisi politikası', 'FDA yolu']),
]
for i, (t, col, items) in enumerate(cols):
    x = 48 + i * 292
    card(x, 170, 276, 240)
    c.setFillColor(col)
    c.roundRect(x, 350, 276, 60, 18, fill=1, stroke=0)
    c.rect(x, 350, 276, 20, fill=1, stroke=0)
    text(x + 22, 372, t, 'B', 20, white)
    yy = 318
    for it in items:
        dot(x + 28, yy + 5, 5, col)
        yy = text(x + 42, yy, it, 'R', 14, INK, 216, 18) - 12
text(48, 130, 'Uygulama ülke seçimine göre metin ve acil numarayı (112 / 911) zaten değiştiriyor.', 'R', 13, INK_S)

# ------------------------------------------------------------------ 9. roadmap
slide('Önerilen sıra', 'Yol haritası', TEAL)
phases = [
    (TEAL, 'Şimdi', ['Veri sorumlusunu belirle', 'Metinleri hukukçuya ver', 'Etik kurul başvurusu', 'SMS izni beyanı']),
    (PURPLE, 'Pilot çalışma', ['Gerçek kafa bandı + saat', 'Gönüllülerle veri', 'Performansı ölç', 'Modeli gerekirse yeniden eğit']),
    (CORAL, 'Tıbbi cihaz süreci', ['Sınıf ve standartlar', 'Klinik değerlendirme', 'Onaylanmış kuruluş', 'TİTCK / CE (ABD: FDA)']),
    (MINT, 'Yayın', ['Google Play beyanları', 'Web’de gizlilik politikası', 'Güvenlik incelemesi', 'Destek ve izleme']),
]
c.setFillColor(LINE)
c.rect(80, 348, 800, 6, fill=1, stroke=0)
for i, (col, t, items) in enumerate(phases):
    x = 48 + i * 222
    dot(x + 32, 351, 20, col, str(i + 1), 18)
    text(x + 4, 310, t, 'B', 18, col)
    card(x, 130, 206, 160)
    yy = 258
    for it in items:
        dot(x + 20, yy + 5, 4, col)
        yy = text(x + 32, yy, it, 'R', 13.5, INK, 164, 17) - 10

# ------------------------------------------------------------------ 10. first steps
slide('İlk üç adım', 'Bu hafta başlanabilir', TEAL)
first = [
    ('1', 'Veri sorumlusunu belirle', 'Kim / hangi kurum? İletişim adresi ne? Metinlerdeki boş yer doldurulur.'),
    ('2', 'Metinleri hukukçuya ver', 'Uygulamadaki tüm metinler tek klasörde (assets/legal); hukukçu doğrudan okuyabilir.'),
    ('3', 'Pilot çalışmayı planla', 'Danışman doktor ve okul ile etik kurul başvurusunu konuş.'),
]
for i, (n, t, s) in enumerate(first):
    x = 48 + i * 292
    card(x, 170, 276, 230)
    dot(x + 56, 340, 34, TEAL, n, 30)
    yy = text(x + 24, 268, t, 'B', 18, INK, 230)
    text(x + 24, yy - 6, s, 'R', 13.5, INK_S, 230, 18)
text(48, 84, 'Ayrıntılı liste (ne ve neden): docs/EpiProt-uygulamaya-gecis-yapilacaklar.md · Uygulamadaki senaryolar: mobile-app/android/PRIVACY.md',
     'R', 12, INK_S, 860)

c.save()
print(OUT, page[0], 'pages')
