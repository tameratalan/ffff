# Film Sahnesi

E-ticaret demo otomasyon aracı — organik arama, hit simülasyonu, sıralama takibi.

## Kurulum

**Windows**
```bat
setup.bat
```

**macOS**
```bash
cd ~/Desktop/ffff
./setup.sh
```
veya Finder'da `setup.command` dosyasına çift tıklayın.

## Çalıştırma

**Windows**
```bat
baslat.bat
```

**macOS**
```bash
./baslat.sh
```
veya `baslat.command` dosyasına çift tıklayın.

## Gereksinimler

- Python 3.11+ (Mac: `brew install python@3.12 python-tk@3.12`)
- Chrome
- `pip install -r requirements.txt`
- `playwright install chromium`

## Mac — ilk kullanım

1. `hesaplar.txt.example` → `hesaplar.txt` kopyalayın, hesapları girin (`eposta:sifre`)
2. `sahne_config.toml` ayarlarını düzenleyin
3. `./sahne_giris.sh` — hesaplara giriş
4. `./baslat.sh` — GUI
