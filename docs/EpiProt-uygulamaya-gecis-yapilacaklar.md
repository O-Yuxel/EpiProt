# EpiProt gerçek kullanıma geçmeden önce yapılması gerekenler

Bu liste, uygulamanın kendi içinde yapılamayan, ama EpiProt gerçek hastalarla kullanılacaksa **mutlaka** yapılması gereken
işleri toplar. Her madde için **ne** yapılacağı ve **neden** gerektiği yazılı. Hukuki görüş değildir; her madde ilgili
uzmanla (avukat, düzenleyici danışman, etik kurul) kontrol edilmelidir.

Öncelik: 🔴 olmadan başlanamaz · 🟠 yayından önce gerekli · 🟢 kısa süre içinde yapılmalı

---

## 1. Hukuk ve gizlilik belgeleri

| # | Ne yapılmalı | Neden | Öncelik |
|---|---|---|---|
| 1.1 | **Veri sorumlusunu belirle** (kim / hangi kurum, iletişim adresi) ve uygulamadaki metinlere yaz. | KVKK m.10 ve GDPR m.13 aydınlatma metninde veri sorumlusunun kimliğini zorunlu tutar. Metinlerde şu an boş bir yer var. | 🔴 |
| 1.2 | **Türk hukukçuya metinleri kontrol ettir** (aydınlatma metni, 4 açık rıza metni, sınırlar sayfası). | Metinler taslak. Hatalı veya eksik bir rıza geçersiz sayılır; o zaman sağlık verisinin işlenmesi hukuka aykırı olur. | 🔴 |
| 1.3 | **VERBİS kaydını değerlendir** (Veri Sorumluları Sicili). | Ana faaliyeti sağlık verisi işlemek olan veri sorumluları genelde kayıttan muaf değildir. | 🟠 |
| 1.4 | **Risk değerlendirmesi (DPIA) yaz**: hangi veri, hangi risk, nasıl önleniyor. | GDPR m.35 büyük ölçekli sağlık verisi için zorunlu tutar; KVKK açısından da iyi uygulamadır. Sorun çıkarsa “gerekli önlemi aldık” demenin kanıtıdır. | 🟠 |
| 1.5 | **Herkese açık bir web sayfasında gizlilik politikası** yayınla (uygulamadaki metnin aynısı). | Google Play, sağlık uygulamalarında bu bağlantıyı zorunlu tutar. | 🟠 |
| 1.6 | **Veri ihlali müdahale planı** hazırla: kim, neyi, ne kadar sürede bildirir. | KVKK ve GDPR’da ihlal 72 saat içinde bildirilmeli; ABD’de FTC kuralı da bildirim ister. Plan olmazsa süre kaçar. | 🟢 |
| 1.7 | **Hak başvurusu kanalı** kur (e-posta veya form) ve cevap süresini belirle. | KVKK’da başvuru 30 gün içinde, GDPR’da 1 ay içinde cevaplanmalı. Uygulama içi indirme ve silme var ama iletişim kanalı da gerekli. | 🟢 |

## 2. Tıbbi cihaz mevzuatı (en büyük iş)

| # | Ne yapılmalı | Neden | Öncelik |
|---|---|---|---|
| 2.1 | **Ürünün tıbbi cihaz sınıfını belirle** (Türkiye TİTCK ve AB MDR; MDR Kural 11 yazılım). | Nöbet algılayıp alarm veren yazılım tıbbi amaçlıdır. Tıbbi cihaz olarak kabul edilir, büyük olasılıkla en az sınıf IIa. | 🔴 |
| 2.2 | **Kalite ve yazılım süreçlerini kur**: ISO 13485 (kalite yönetimi), IEC 62304 (yazılım yaşam döngüsü), ISO 14971 (risk yönetimi), IEC 62366 (kullanılabilirlik). | CE işareti ve TİTCK kaydı bu belgeler ve süreçler olmadan alınamaz. | 🔴 |
| 2.3 | **CE işareti** için onaylanmış kuruluş (notified body) ile çalış. | Sınıf IIa ve üzeri cihazlar kendi beyanıyla değil, onaylanmış kuruluş denetimiyle piyasaya çıkar. | 🔴 |
| 2.4 | **ABD’de kullanılacaksa FDA yolunu belirle** (benzer ürünler 510(k) ile onaylandı, örneğin Empatica Embrace). | FDA onayı olmadan ABD’de tıbbi iddiayla satılamaz. | 🔴 (ABD için) |
| 2.5 | Bu süreçler bitene kadar **“araştırma prototipi” olarak kalmasını** sağla (uygulamada yazıyor). | Onaysız ürünün tıbbi cihaz gibi sunulması yasaktır. | 🔴 |
| 2.6 | **Kafa bandı donanımının testleri**: elektrik güvenliği IEC 60601-1 ve evde kullanım IEC 60601-1-11, elektromanyetik uyumluluk IEC 60601-1-2, deriye temas eden malzemeler ISO 10993 (silikon, pedler), lityum pil IEC 62133, su/ter dayanımı (IP67 hedefi) testi. | Kafa bandı hastanın başına takılan, pilli ve radyolu bir tıbbi cihaz; bu testler olmadan güvenli olduğu gösterilemez. Tasarım (HARDWARE.md) bunlara göre yapıldı ama hiçbiri test edilmedi. | 🔴 |
| 2.7 | **Radyo onayı**: Bluetooth modülü önceden sertifikalı (FCC, CE), ama bitmiş ürün için RED (AB) / FCC beyanı ve Türkiye için BTK uygunluğu yine gerekir. | Sertifikalı modül işi kolaylaştırır, son ürünün beyanını ortadan kaldırmaz. | 🟠 |

## 3. Klinik doğrulama ve etik

| # | Ne yapılmalı | Neden | Öncelik |
|---|---|---|---|
| 3.1 | **Gerçek EpiProt cihazıyla veri toplama çalışması** planla. | Model hastane verisiyle (SeizeIT2) ve simüle edilmiş saat nabzıyla eğitildi. Gerçek kafa bandı ve gerçek saatle hiç doğrulanmadı. | 🔴 |
| 3.2 | **Etik kurul onayı** al; gönüllüler ve veliler için **araştırma onam formlarını** hazırla. | İnsan katılımcılı sağlık araştırması etik kurul onayı olmadan yapılamaz. Bu formlar uygulamadaki rızalardan ayrı belgelerdir. | 🔴 |
| 3.3 | Klinik araştırma izni gerekip gerekmediğini **TİTCK ile netleştir**. | Tıbbi cihazla yapılan klinik araştırmalar ayrıca izne tabi olabilir. | 🟠 |
| 3.4 | **Gerçek kullanımda performansı ölç**: kaçırılan nöbet, günlük yanlış alarm, gecikme. | Laboratuvar sonucu (54/55, günde 0,24 yanlış alarm) gerçek hayatta farklı çıkabilir. Hem güvenlik hem tıbbi cihaz dosyası için gerekli. | 🟠 |
| 3.5 | **Gerçek saat verisiyle yanlış nabız kontrollerini ayarla**: “takılı nabız” eşiği (şu an 1 dakikada 1 atımdan az değişim) ve bilek hareketi ritmiyle nabız karşılaştırması. | Simülasyonda takılı nabız 55 nöbetten 15’ini kaçırtıyordu, eklenen kontrolle 53/55’e çıktı; ama gerçek saatlerin nasıl takıldığı bilinmiyor. Sahte yüksek nabız (spor, yürüme) yanlış alarmı 0,24’ten 0,39’a çıkarıyor; çözümü gerçek bilek verisi gerektiriyor. | 🟠 |
| 3.6 | **Kafa bandının hareket sensörünü doğrula**: SeizeIT2’de hareket sensörü ensedeki kayıt cihazındaydı, EpiProt kafa bandında boynun yanındaki podda ve başla birlikte hareket ediyor. | Hareket verisi 55 nöbetten 5’inin yakalanmasını sağlıyor (hareketle 54/55, hareketsiz 49/55). Baş hareketi (konuşma, başını çevirme) farklı görünebilir; gerçek kayıtlarla kontrol edilmeli, gerekirse model yeniden eğitilmeli. | 🔴 |
| 3.7 | **Pedlerin sinyal kalitesini ve kafa bandının rahatlığını gerçek prototiple ölç**: yarı kuru pedlerin kulak arkasında temas direnci, gece boyu takma, 5 kafa ölçüsünde hesaplanan kuvvetlerin kuvvet ölçerle doğrulanması. | Basınç, kafada durma ve yastık hesapları yalnızca dijital kafa modelleri üzerinde yapıldı (device-firmware/cad). | 🔴 |

## 4. Google Play ve teknik yayın

| # | Ne yapılmalı | Neden | Öncelik |
|---|---|---|---|
| 4.1 | **SMS izni beyanı** (Play Console → hassas izinler; “acil durum uyarısı” istisnası). | SEND_SMS kısıtlı bir izin. Beyan kabul edilmezse uygulama yayından kaldırılır. Reddedilirse mesajı telefonun kendi SMS uygulamasıyla göndermeye geçilmeli. | 🔴 |
| 4.1b | **SMS okuma izni beyanı** (RECEIVE_SMS): bakıcı modu ve "geliyorum" cevabı EpiProt SMS'lerini okur. | Google Play, SMS okuma iznini yalnızca kabul ettiği kullanımlarda verir; beyan reddedilirse bakıcı alarmı için bildirim tabanlı başka bir yol (ör. push) gerekir. | 🔴 |
| 4.1c | **Hedef Android sürümünü 35'e (Android 15) çıkar** ve yeniden test et. | Google Play yeni uygulamalarda güncel hedef sürüm ister; uygulama şu an 34'ü hedefliyor. | 🔴 |
| 4.2 | **Data safety formu** ve **sağlık uygulaması beyanı** doldur. | Google Play sağlık verisi işleyen uygulamalarda bunları zorunlu tutar. | 🔴 |
| 4.3 | **Yayın imza anahtarını** oluştur ve güvenle sakla (telefon ve saat aynı anahtar). | Telefon ve saat aynı anahtarla imzalanmazsa birbirini bulamaz. Anahtar kaybolursa güncelleme yapılamaz. | 🔴 |
| 4.4 | **Bağımsız güvenlik incelemesi** (kod ve sızma testi). | Sağlık verisi işleyen uygulamada güvenlik açığı hem hasta için risk hem de hukuki sorumluluktur. | 🟠 |
| 4.5 | **Kafa bandı prototipini üret ve yazılımını (firmware) yaz**: devre kartı, parçalar, kafa bandı yazılımı. Bluetooth protokolü (PROTOCOL.md), telefon tarafı, şifreli eşleştirme ve sanal kafa bandı hazır; ikinci telefonla gerçek Bluetooth üzerinden test edildi. | Gerçek kafa bandı henüz yok; telefon şu an kayıtlı gerçek nöbet verisini oynatan test kafa bandıyla çalışıyor. | 🔴 |
| 4.6 | **Pil optimizasyonu muafiyeti** için Play politikasına uygunluğu beyan et. | Uygulama nöbet alarmı için pil optimizasyonundan muafiyet istiyor; Google Play bu izni yalnızca gerekçeli kullanımlarda kabul ediyor. | 🟠 |
| 4.7 | **Gerçek telefonda ve saatte 24 saatlik pil ve kesintisizlik testi** yap (farklı markalar, özellikle Xiaomi ve Samsung). | Bilgisayardaki 24 saatlik test hız ve belleği doğruladı; pil tüketimi ve markaların uygulamayı kapatma davranışı ancak gerçek cihazda ölçülür. | 🔴 |

## 5. Ülkeye özel işler

| # | Ne yapılmalı | Neden | Öncelik |
|---|---|---|---|
| 5.1 | **AB:** metinleri kullanılacak ülkelerin **dillerine profesyonelce çevirt**; AB dışından sunuluyorsa **AB temsilcisi** ata (GDPR m.27). | Aydınlatma kişinin anlayacağı dilde olmalı. AB dışındaki veri sorumluları AB’de bir temsilci göstermek zorunda. | 🟠 (AB için) |
| 5.2 | **ABD:** metinleri **ABD’li bir avukata** kontrol ettir. | Eyalet yasaları farklı; Washington’da kullanıcı doğrudan dava açabiliyor. | 🔴 (ABD için) |
| 5.3 | **ABD:** 13 yaş altı için **FTC onaylı veli doğrulama yöntemi** ekle (imzalı form, eğitimli personel kontrolü vb.). | COPPA, velinin gerçekten veli olduğunun doğrulanmasını ister. Uygulama şu an sadece yazılı imzayı kaydediyor. | 🔴 (ABD için) |
| 5.4 | **ABD:** mağaza sayfasından bağlantı verilen ayrı bir **“Consumer Health Data Privacy Policy”** yayınla. | Washington My Health My Data Act bunu ayrıca ister. | 🟠 (ABD için) |

## 6. Sürekli yapılacaklar

| # | Ne yapılmalı | Neden |
|---|---|---|
| 6.1 | Metinler değiştiğinde uygulamadaki **metin sürümünü** (`TEXT_VERSION`) artır. | Uygulama bu sürüm değişince herkese kurulumu yeniden gösterir; yeni metne yeni onay alınmış olur. |
| 6.2 | Yasa değişikliklerini **yılda en az bir kez** gözden geçir. | KVKK 2024’te, KVKK Kurulu kararları 2026’da değişti; kurallar hareketli. |
| 6.3 | Yanlış alarm ve kaçırılan nöbet şikâyetlerini **kayıt altına al** ve incele. | Tıbbi cihazlarda piyasa sonrası gözetim zorunludur. |

---

### Uygulamada hazır olanlar (bu listeye girmedi)

İlk açılışta 12 adımlık kurulum (ülke seçimi, karar veren kişi, aydınlatma, sınırlar, 4 ayrı rıza, izin açıklamaları,
özet) · Gizlilik Merkezi (rızaları değiştirme, onay geçmişi, verilerimi indir, tüm verilerimi sil) · ülkeye göre
metinler (Türkiye, AB, ABD) · 13 yaş altı için veli onayı ekranı (ABD) · çocuklar için sade anlatım · 18 yaş hatırlatması ·
bakıcı onayı ve bakıcıya bilgilendirme SMS’i · şifreli veritabanı ve şifreli ayarlar · yedekleme ve cihaz taşımada veri
dışarı çıkmıyor · uygulama kilidi · rıza yoksa saat sensörleri kapalı · doktor raporu (PDF, hasta istediği uygulamayla
gönderir; ayrı onayla alarm anının EEG, hareket ve nabız grafikleri). Ayrıntılar: `mobile-app/android/PRIVACY.md`.
