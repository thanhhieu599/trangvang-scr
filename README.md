# Công cụ thu thập danh bạ doanh nghiệp (Trang Vàng)

Lấy **Tên, Địa chỉ, Điện thoại, Email, Website** của các công ty theo Lĩnh vực > Phân ngành > Công ty, xuất ra Excel.

> Trang Vàng **chặn truy cập tự động** (lỗi 403 / "connection forcibly closed"). Vì vậy cách chính là
> **người mở trang như bình thường, công cụ chỉ đọc dữ liệu trên trang đang mở**: Cách A hoặc Cách B.
> Cách C (máy tự cào) chỉ dùng được với website cho phép truy cập tự động; khi bị chặn, công cụ tự dừng để tránh bị khóa IP.

## Chạy bằng terminal (không cần giao diện)

Terminal chạy nền và theo dõi thư mục `trang_da_luu`. Mỗi khi anh/chị lưu một trang Trang Vàng vào đó (`Ctrl+S`), terminal tự đọc dữ liệu và cập nhật `cong_ty.xlsx` trong vài giây.

```bash
pip install -r requirements.txt
```
```bash
python scraper.py watch
```

Trên Windows có thể chạy `chay.bat` thay cho 2 lệnh trên.

Tùy chọn:

```bash
python scraper.py watch --dir "C:\Users\letha\Downloads" --sector "Hóa chất" --out hoa_chat.xlsx
```

- `--dir`: thư mục theo dõi. Có thể trỏ thẳng vào thư mục Downloads, công cụ tự bỏ qua file không phải của Trang Vàng.
- Trang danh sách cho Tên, Địa chỉ, SĐT, Website. Lưu thêm trang chi tiết công ty để có Email, email tự gộp vào đúng công ty.
- File Excel đang mở thì công cụ lưu tạm sang tên khác, không báo lỗi.
- Tắt rồi bật lại không đọc lại file cũ, dữ liệu cộng dồn.
- Xem tổng số: `python scraper.py status`. Xuất lại file: `python scraper.py export --out cong_ty.xlsx`.

Mẹo: trong Chrome vào Cài đặt > Tệp đã tải xuống, chọn thư mục `trang_da_luu`, và lưu bằng **"Webpage, HTML only"** cho nhanh.

## Cách A (khuyên dùng): Nút thu thập trên Chrome/Edge

Không cần cài Python.

1. Mở file `cai_dat_bookmarklet.html` bằng Chrome và **kéo nút vàng "📥 Thu thập D&T" lên thanh dấu trang**.
2. Vào Trang Vàng, mở trang danh sách công ty của một phân ngành rồi **bấm nút**. Góc phải hiện "Đã có N công ty".
3. Sang trang 2, 3… và các phân ngành khác, bấm nút ở mỗi trang. Dữ liệu cộng dồn, không trùng.
4. Muốn lấy email: vào trang chi tiết công ty và bấm nút. Trang danh sách thường không hiện email.
5. Bấm **Tải Excel (CSV)** để tải file.

Năng suất: ~20 công ty/lần bấm, một người làm khoảng 1.000+ công ty/giờ.

## Cách B: Lưu trang (Ctrl+S) rồi cho Python đọc

Hợp với việc giao cho nhân viên hoặc cộng tác viên, sau đó gom file lại một chỗ:

1. Ở mỗi trang danh sách hoặc trang chi tiết công ty, bấm `Ctrl+S`, chọn **"Webpage, HTML only"** và lưu vào thư mục `trang_da_luu`.
2. Chạy:

```bash
pip install -r requirements.txt
```
```bash
python scraper.py import-html --dir trang_da_luu --sector "Hóa chất" --out hoa_chat.xlsx
```

Chạy lại sau khi lưu thêm trang: không trùng, và trang chi tiết tự bổ sung email vào công ty đã có.

## Cách C: Máy tự cào (chỉ khi website cho phép)

### Cài đặt

```bash
pip install -r requirements.txt
```

### Chạy

**Chạy thử 20 công ty trước** để kiểm tra dữ liệu ra đúng:

```bash
python scraper.py crawl --start-url "<link trang tổng lĩnh vực>" --max-companies 20 --out thu.xlsx
```

**Chỉ cào 1 lĩnh vực** (vd. Bảo hộ lao động — khách/đối thủ trực tiếp của D&T):

```bash
python scraper.py crawl --start-url "<link trang tổng lĩnh vực>" --only-sector "Bảo hộ" --out bao_ho.xlsx
```

**Cào thẳng 1 phân ngành** (dán link trang danh sách công ty như hình 4):

```bash
python scraper.py crawl --start-url "https://trangvangvietnam.com/categories/484645/hoa-chat-....html" --out hoa_chat.xlsx
```

`--start-url` nhận được 3 loại link: trang tổng các lĩnh vực, trang 1 lĩnh vực, hoặc link phân ngành. Dùng nhiều lần `--start-url` để chạy nhiều link.

**Xem tiến độ / xuất file bất kỳ lúc nào:**

```bash
python scraper.py status
python scraper.py export --out cong_ty.xlsx
```

## 3. Bị ngắt giữa chừng?

Nhấn `Ctrl+C` hoặc mất mạng đều không sao. Chạy lại **đúng lệnh cũ**: công cụ làm tiếp từ phân ngành/trang đang dở, không cào lại công ty đã có (tiến độ lưu trong `trangvang.db`).
Muốn quét lại danh sách phân ngành (khi website thêm ngành mới) thì thêm `--rediscover`.

## 4. Tùy chọn

| Tham số | Ý nghĩa |
|---|---|
| `--delay 2` | Nghỉ ~2 giây giữa 2 lần tải trang. Đừng để dưới 1.5 giây để tránh bị chặn IP. |
| `--max-pages 500` | Giới hạn số trang mỗi phân ngành |
| `--max-companies N` | Dừng sau N công ty (chạy thử) |
| `--only-sector "Hóa chất"` | Chỉ lấy lĩnh vực có tên chứa chuỗi này (dùng nhiều lần được) |
| `--sector-pattern "/nganh/"` | Regex URL trang lĩnh vực nếu công ty không tự nhận diện đúng |

## 5. Cách nhận diện dữ liệu

Không phụ thuộc tên class CSS (web đổi giao diện vẫn chạy):

- Phân ngành = link có `/categories/<số>`; công ty = link có `/listings/<số>`; phân trang bằng `?page=N`, dừng khi trang không còn công ty mới.
- Điện thoại = link `tel:` (bỏ số Fax); email = `mailto:` hoặc email bị Cloudflare ẩn (tự giải mã); website = link ra ngoài, loại Facebook/Zalo/Google...; địa chỉ = dòng cạnh icon định vị.
- Một công ty nằm ở nhiều phân ngành chỉ cào 1 lần; cột "Tất cả phân ngành" ghi đủ.

Nếu website đổi mẫu link, sửa `CATEGORY_RE` / `LISTING_RE` ở đầu `scraper.py`.

## 6. Thời gian ước tính

Mỗi công ty ~1 request. Với delay 2s: ~1.800 công ty/giờ. Lĩnh vực Bảo hộ lao động (~7.900 DN) mất khoảng 4–5 giờ; toàn bộ danh bạ (hàng trăm nghìn DN) mất nhiều ngày, nên **cào theo lĩnh vực ưu tiên**.

## 7. Lưu ý pháp lý khi dùng dữ liệu

- Đọc Điều khoản sử dụng của website nguồn; chỉ dùng cho nghiên cứu thị trường / tìm khách hàng B2B nội bộ, không bán lại dữ liệu.
- Email/SĐT đứng tên cá nhân là dữ liệu cá nhân theo **Nghị định 13/2023/NĐ-CP**; gửi email/SMS quảng cáo phải tuân thủ **Nghị định 91/2020/NĐ-CP** về chống tin nhắn, thư điện tử rác (có cách từ chối nhận, không gửi hàng loạt khi chưa đồng ý).

## Test

```bash
pip install pytest && python -m pytest tests -q
```
