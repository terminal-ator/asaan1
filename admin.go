package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"html/template"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

type adminItem struct {
	Name, SKU, Unit           string
	Quantity, Rate, LineTotal int64
}
type adminOrder struct {
	ID, Number, Notes string
	Shop              Shop
	Total             int64
	CreatedAt         time.Time
	Items             []adminItem
}
type productFormData struct {
	Product Product
	Active  bool
	Error   string
}
type importPageData struct {
	Imported int
	Error    string
}

func adminAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		cookie, err := c.Request.Cookie("ordex_admin")
		if err != nil || !validAdminSession(cookie.Value) {
			c.Redirect(http.StatusSeeOther, "/admin/login")
			c.Abort()
			return
		}
		c.Next()
	}
}

func adminPassword() string {
	if value := os.Getenv("ADMIN_PASSWORD"); value != "" {
		return value
	}
	return "ordex-admin"
}
func adminSecret() string {
	if value := os.Getenv("ADMIN_SESSION_SECRET"); value != "" {
		return value
	}
	return "local-" + adminPassword()
}
func signAdmin(value string) string {
	mac := hmac.New(sha256.New, []byte(adminSecret()))
	mac.Write([]byte(value))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
func makeAdminSession() string {
	value := base64.RawURLEncoding.EncodeToString([]byte(fmt.Sprintf("admin|%d", time.Now().Add(24*time.Hour).Unix())))
	return value + "." + signAdmin(value)
}
func validAdminSession(session string) bool {
	parts := strings.Split(session, ".")
	if len(parts) != 2 || !hmac.Equal([]byte(signAdmin(parts[0])), []byte(parts[1])) {
		return false
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return false
	}
	fields := strings.Split(string(raw), "|")
	if len(fields) != 2 || fields[0] != "admin" {
		return false
	}
	expiry, err := strconv.ParseInt(fields[1], 10, 64)
	return err == nil && time.Now().Unix() < expiry
}
func adminLoginPage() gin.HandlerFunc {
	return func(c *gin.Context) { renderAdmin(c, "login.html", gin.H{"Error": c.Query("error") != ""}) }
}
func adminLogin() gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.PostForm("password") != adminPassword() {
			c.Redirect(http.StatusSeeOther, "/admin/login?error=1")
			return
		}
		secure := c.Request.TLS != nil || c.GetHeader("X-Forwarded-Proto") == "https"
		http.SetCookie(c.Writer, &http.Cookie{Name: "ordex_admin", Value: makeAdminSession(), Path: "/", HttpOnly: true, SameSite: http.SameSiteLaxMode, Secure: secure, MaxAge: 86400})
		c.Redirect(http.StatusSeeOther, "/admin")
	}
}
func adminLogout() gin.HandlerFunc {
	return func(c *gin.Context) {
		http.SetCookie(c.Writer, &http.Cookie{Name: "ordex_admin", Value: "", Path: "/", MaxAge: -1})
		c.Redirect(http.StatusSeeOther, "/admin/login")
	}
}

func adminDashboard(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		orders, err := loadOrders(c, db, c.Query("q"), c.Query("date"))
		if err != nil {
			c.String(500, "Could not load orders")
			return
		}
		renderAdmin(c, ordersTemplate, gin.H{"Orders": orders, "Query": c.Query("q"), "Date": c.Query("date")})
	}
}

func exportOrders(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		orders, err := loadOrders(c, db, c.Query("q"), c.Query("date"))
		if err != nil {
			c.String(500, "Could not export orders")
			return
		}
		c.Header("Content-Disposition", "attachment; filename=ordex-orders.csv")
		c.Header("Content-Type", "text/csv; charset=utf-8")
		w := csv.NewWriter(c.Writer)
		defer w.Flush()
		_ = w.Write([]string{"Order", "Received at", "Shop", "Contact", "Mobile", "Address", "Latitude", "Longitude", "Item", "SKU", "Unit", "Quantity", "Rate (INR)", "Line total (INR)", "Order total (INR)", "Notes"})
		for _, order := range orders {
			for _, item := range order.Items {
				_ = w.Write([]string{order.Number, order.CreatedAt.Format(time.RFC3339), order.Shop.StoreName, order.Shop.CustomerName, order.Shop.Mobile, order.Shop.Address, fmt.Sprint(order.Shop.Latitude), fmt.Sprint(order.Shop.Longitude), item.Name, item.SKU, item.Unit, fmt.Sprint(item.Quantity), moneyINR(item.Rate), moneyINR(item.LineTotal), moneyINR(order.Total), order.Notes})
			}
		}
	}
}

func loadOrders(c *gin.Context, db *sql.DB, query, date string) ([]adminOrder, error) {
	rows, err := db.QueryContext(c, `SELECT id, order_number, shop_json, notes, total, created_at FROM orders ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	orders := []adminOrder{}
	needle := strings.ToLower(strings.TrimSpace(query))
	for rows.Next() {
		var order adminOrder
		var shopJSON []byte
		if err := rows.Scan(&order.ID, &order.Number, &shopJSON, &order.Notes, &order.Total, &order.CreatedAt); err != nil {
			return nil, err
		}
		_ = json.Unmarshal(shopJSON, &order.Shop)
		if needle != "" && !strings.Contains(strings.ToLower(order.Number+" "+order.Shop.StoreName+" "+order.Shop.Mobile+" "+order.Shop.CustomerName), needle) {
			continue
		}
		if date != "" && order.CreatedAt.Format("2006-01-02") != date {
			continue
		}
		items, err := db.QueryContext(c, `SELECT name, sku, unit, quantity, rate, line_total FROM order_items WHERE order_id = ?`, order.ID)
		if err != nil {
			return nil, err
		}
		for items.Next() {
			var item adminItem
			if err := items.Scan(&item.Name, &item.SKU, &item.Unit, &item.Quantity, &item.Rate, &item.LineTotal); err != nil {
				items.Close()
				return nil, err
			}
			order.Items = append(order.Items, item)
		}
		items.Close()
		orders = append(orders, order)
	}
	return orders, rows.Err()
}

func productList(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		rows, err := db.QueryContext(c, `SELECT id, sku, name, simple_name, company, brand, category, packing, unit, rate, mrp, image_url, updated_at, created_at, active FROM products ORDER BY company, brand, name`)
		if err != nil {
			c.String(500, "Could not load products")
			return
		}
		defer rows.Close()
		type record struct {
			Product
			Active bool
		}
		products := []record{}
		for rows.Next() {
			var p Product
			var updated, created time.Time
			var active bool
			if err := rows.Scan(&p.ID, &p.SKU, &p.Name, &p.SimpleName, &p.Company, &p.Brand, &p.Category, &p.Packing, &p.Unit, &p.Rate, &p.MRP, &p.ImageURL, &updated, &created, &active); err != nil {
				c.String(500, "Could not load products")
				return
			}
			p.UpdatedAt = updated.Format(time.RFC3339)
			p.CreatedAt = created.Format(time.RFC3339)
			products = append(products, record{p, active})
		}
		renderAdmin(c, productsTemplate, gin.H{"Products": products})
	}
}

func productImportPage() gin.HandlerFunc {
	return func(c *gin.Context) { renderAdmin(c, importTemplate, importPageData{}) }
}

func productImportTemplate() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Content-Disposition", "attachment; filename=ordex-product-import-template.csv")
		c.Header("Content-Type", "text/csv; charset=utf-8")
		w := csv.NewWriter(c.Writer)
		defer w.Flush()
		_ = w.Write([]string{"sku", "name", "simple_name", "company", "brand", "category", "packing", "unit", "sale_rate", "mrp", "image_url", "active"})
		_ = w.Write([]string{"SURF-1KG-12", "ERP: SURF EXCEL EASY WASH 1KG CASE 12", "Surf Excel 1 kg", "HUL", "Surf Excel", "Detergent", "1 kg × 12", "case", "1788.00", "2160.00", "", "true"})
	}
}

func importProducts(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 5<<20)
		file, err := c.FormFile("file")
		if err != nil {
			renderAdmin(c, importTemplate, importPageData{Error: "Choose a CSV file (maximum 5 MB)."})
			return
		}
		f, err := file.Open()
		if err != nil {
			renderAdmin(c, importTemplate, importPageData{Error: "Could not read the file."})
			return
		}
		defer f.Close()
		r := csv.NewReader(f)
		r.TrimLeadingSpace = true
		headers, err := r.Read()
		if err != nil {
			renderAdmin(c, importTemplate, importPageData{Error: "The CSV needs a header row."})
			return
		}
		positions := map[string]int{}
		for i, header := range headers {
			positions[strings.TrimSpace(header)] = i
		}
		required := []string{"sku", "name", "company", "brand", "category", "packing", "unit", "sale_rate", "mrp"}
		for _, name := range required {
			if _, ok := positions[name]; !ok {
				renderAdmin(c, importTemplate, importPageData{Error: "Missing required column: " + name})
				return
			}
		}
		tx, err := db.BeginTx(c, nil)
		if err != nil {
			renderAdmin(c, importTemplate, importPageData{Error: "Could not start import."})
			return
		}
		defer tx.Rollback()
		count := 0
		for line := 2; ; line++ {
			record, readErr := r.Read()
			if readErr != nil {
				if readErr == io.EOF {
					break
				}
				renderAdmin(c, importTemplate, importPageData{Error: fmt.Sprintf("Could not read row %d.", line)})
				return
			}
			get := func(name string) string {
				i, ok := positions[name]
				if !ok || i >= len(record) {
					return ""
				}
				return strings.TrimSpace(record[i])
			}
			rate, rateErr := parsePaise(get("sale_rate"))
			mrp, mrpErr := parsePaise(get("mrp"))
			p := Product{SKU: get("sku"), Name: get("name"), SimpleName: get("simple_name"), Company: get("company"), Brand: get("brand"), Category: get("category"), Packing: get("packing"), Unit: get("unit"), Rate: rate, MRP: mrp, ImageURL: get("image_url")}
			if rateErr != nil || mrpErr != nil || p.SKU == "" || p.Name == "" || p.Company == "" || p.Brand == "" || p.Category == "" || p.Packing == "" || p.Unit == "" {
				renderAdmin(c, importTemplate, importPageData{Error: fmt.Sprintf("Row %d has missing or invalid values.", line)})
				return
			}
			active := strings.ToLower(get("active")) != "false"
			now := time.Now().UTC()
			_, err = tx.ExecContext(c, `INSERT INTO products (id,sku,name,simple_name,company,brand,category,packing,unit,rate,mrp,image_url,active,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET name=excluded.name,simple_name=excluded.simple_name,company=excluded.company,brand=excluded.brand,category=excluded.category,packing=excluded.packing,unit=excluded.unit,rate=excluded.rate,mrp=excluded.mrp,image_url=excluded.image_url,active=excluded.active,updated_at=excluded.updated_at`, uuid.NewString(), p.SKU, p.Name, p.SimpleName, p.Company, p.Brand, p.Category, p.Packing, p.Unit, p.Rate, p.MRP, p.ImageURL, active, now, now)
			if err != nil {
				renderAdmin(c, importTemplate, importPageData{Error: fmt.Sprintf("Row %d could not be saved.", line)})
				return
			}
			count++
		}
		if err = tx.Commit(); err != nil {
			renderAdmin(c, importTemplate, importPageData{Error: "Could not complete import."})
			return
		}
		renderAdmin(c, importTemplate, importPageData{Imported: count})
	}
}

func editProduct(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		var p Product
		var updated time.Time
		var active bool
		var created time.Time
		err := db.QueryRowContext(c, `SELECT id, sku, name, simple_name, company, brand, category, packing, unit, rate, mrp, image_url, updated_at, created_at, active FROM products WHERE id = ?`, c.Param("id")).Scan(&p.ID, &p.SKU, &p.Name, &p.SimpleName, &p.Company, &p.Brand, &p.Category, &p.Packing, &p.Unit, &p.Rate, &p.MRP, &p.ImageURL, &updated, &created, &active)
		if errorsIsNoRows(err) {
			c.Status(404)
			return
		}
		if err != nil {
			c.String(500, "Could not load product")
			return
		}
		renderAdmin(c, productTemplate, productFormData{Product: p, Active: active})
	}
}

func productForm(_ *sql.DB, p *Product) gin.HandlerFunc {
	return func(c *gin.Context) {
		if p == nil {
			p = &Product{Unit: "case"}
		}
		renderAdmin(c, productTemplate, productFormData{Product: *p, Active: true})
	}
}

func saveProduct(db *sql.DB, update bool) gin.HandlerFunc {
	return func(c *gin.Context) {
		form, err := productFromRequest(c)
		if err != nil {
			renderAdmin(c, productTemplate, productFormData{Product: form, Active: c.PostForm("active") != "", Error: err.Error()})
			return
		}
		if imageURL, imageErr := saveProductImage(c); imageErr != nil {
			renderAdmin(c, productTemplate, productFormData{Product: form, Active: c.PostForm("active") != "", Error: imageErr.Error()})
			return
		} else if imageURL != "" {
			form.ImageURL = imageURL
		}
		if update {
			form.ID = c.Param("id")
			_, err = db.ExecContext(c, `UPDATE products SET sku=?,name=?,simple_name=?,company=?,brand=?,category=?,packing=?,unit=?,rate=?,mrp=?,image_url=?,active=?,updated_at=? WHERE id=?`, form.SKU, form.Name, form.SimpleName, form.Company, form.Brand, form.Category, form.Packing, form.Unit, form.Rate, form.MRP, form.ImageURL, c.PostForm("active") != "", time.Now().UTC(), form.ID)
		} else {
			form.ID = uuid.NewString()
			now := time.Now().UTC()
			_, err = db.ExecContext(c, `INSERT INTO products (id,sku,name,simple_name,company,brand,category,packing,unit,rate,mrp,image_url,active,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`, form.ID, form.SKU, form.Name, form.SimpleName, form.Company, form.Brand, form.Category, form.Packing, form.Unit, form.Rate, form.MRP, form.ImageURL, c.PostForm("active") != "", now, now)
		}
		if err != nil {
			renderAdmin(c, productTemplate, productFormData{Product: form, Active: c.PostForm("active") != "", Error: "Could not save product. SKU must be unique."})
			return
		}
		c.Redirect(http.StatusSeeOther, "/admin/products")
	}
}

func productImageDir() string {
	if path := os.Getenv("PRODUCT_IMAGE_DIR"); path != "" {
		_ = os.MkdirAll(path, 0750)
		return path
	}
	_ = os.MkdirAll("uploads", 0750)
	return "uploads"
}

func saveProductImage(c *gin.Context) (string, error) {
	fileHeader, err := c.FormFile("image")
	if err != nil {
		return "", nil
	}
	if fileHeader.Size > 5<<20 {
		return "", fmt.Errorf("image must be 5 MB or smaller")
	}
	file, err := fileHeader.Open()
	if err != nil {
		return "", fmt.Errorf("could not read image")
	}
	defer file.Close()
	header := make([]byte, 512)
	n, _ := file.Read(header)
	_, _ = file.Seek(0, 0)
	contentType := http.DetectContentType(header[:n])
	extension := map[string]string{"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[contentType]
	if extension == "" {
		return "", fmt.Errorf("upload a JPG, PNG, or WebP image")
	}
	filename := uuid.NewString() + extension
	destination, err := os.OpenFile(filepath.Join(productImageDir(), filename), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0640)
	if err != nil {
		return "", fmt.Errorf("could not save image")
	}
	defer destination.Close()
	if _, err = io.Copy(destination, io.LimitReader(file, 5<<20)); err != nil {
		return "", fmt.Errorf("could not save image")
	}
	return "/uploads/" + filename, nil
}

func deleteProduct(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		if _, err := db.ExecContext(c, "DELETE FROM products WHERE id = ?", c.Param("id")); err != nil {
			c.String(500, "Could not delete product")
			return
		}
		c.Redirect(http.StatusSeeOther, "/admin/products")
	}
}

func productFromRequest(c *gin.Context) (Product, error) {
	rate, err := parsePaise(c.PostForm("rate"))
	if err != nil {
		return Product{}, fmt.Errorf("enter a valid sale rate")
	}
	mrp, err := parsePaise(c.PostForm("mrp"))
	if err != nil {
		return Product{}, fmt.Errorf("enter a valid MRP")
	}
	p := Product{SKU: strings.TrimSpace(c.PostForm("sku")), Name: strings.TrimSpace(c.PostForm("name")), SimpleName: strings.TrimSpace(c.PostForm("simpleName")), Company: strings.TrimSpace(c.PostForm("company")), Brand: strings.TrimSpace(c.PostForm("brand")), Category: strings.TrimSpace(c.PostForm("category")), Packing: strings.TrimSpace(c.PostForm("packing")), Unit: strings.TrimSpace(c.PostForm("unit")), Rate: rate, MRP: mrp, ImageURL: strings.TrimSpace(c.PostForm("imageUrl"))}
	if p.SKU == "" || p.Name == "" || p.Company == "" || p.Brand == "" || p.Category == "" || p.Packing == "" || p.Unit == "" {
		return p, fmt.Errorf("complete all required fields")
	}
	return p, nil
}
func parsePaise(value string) (int64, error) {
	value = strings.TrimSpace(value)
	parts := strings.Split(value, ".")
	if len(parts) > 2 || value == "" {
		return 0, fmt.Errorf("invalid")
	}
	rupees, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil || rupees < 0 {
		return 0, fmt.Errorf("invalid")
	}
	paisa := int64(0)
	if len(parts) == 2 {
		d := parts[1]
		if len(d) > 2 {
			return 0, fmt.Errorf("invalid")
		}
		if len(d) == 1 {
			d += "0"
		}
		paisa, err = strconv.ParseInt(d, 10, 64)
		if err != nil {
			return 0, err
		}
	}
	return rupees*100 + paisa, nil
}
func errorsIsNoRows(err error) bool { return err == sql.ErrNoRows }
func moneyINR(paise int64) string   { return fmt.Sprintf("%.2f", float64(paise)/100) }
func renderAdmin(c *gin.Context, text string, data any) {
	if text == productTemplate {
		text = strings.ReplaceAll(text, `<form method="post"`, `<form enctype="multipart/form-data" method="post"`)
		text = strings.ReplaceAll(text, `<label>Image URL <small>optional</small><input name="imageUrl" value="{{.Product.ImageURL}}"></label>`, `<label>Image URL <small>optional; use this for hosted images</small><input name="imageUrl" value="{{.Product.ImageURL}}"></label><label>Upload image <small>JPG, PNG, or WebP; maximum 5 MB</small><input type="file" name="image" accept="image/jpeg,image/png,image/webp"></label>`)
	}
	if _, err := os.Stat(filepath.Join("templates", text)); err == nil {
		t, parseErr := template.New("layout.html").Funcs(template.FuncMap{"money": moneyINR}).ParseFiles(filepath.Join("templates", "layout.html"), filepath.Join("templates", text))
		if parseErr == nil {
			c.Header("Content-Type", "text/html; charset=utf-8")
			_ = t.ExecuteTemplate(c.Writer, text, data)
			return
		}
	}
	t := template.Must(template.New("admin").Funcs(template.FuncMap{"money": moneyINR, "date": func(t time.Time) string { return t.Local().Format("02 Jan 2006, 03:04 PM") }, "mapURL": func(s Shop) string {
		return fmt.Sprintf("https://www.google.com/maps?q=%f,%f", s.Latitude, s.Longitude)
	}}).Parse(adminLayout + text))
	c.Header("Content-Type", "text/html; charset=utf-8")
	_ = t.Execute(c.Writer, data)
}

const adminLayout = `{{define "nav"}}<nav><a href="/admin">Orders</a><a href="/admin/products">Products</a></nav>{{end}}`
const ordersTemplate = `<!doctype html><title>Ordex admin</title><style>body{font:14px system-ui;margin:0;background:#f5f7f5;color:#17221e}main{max-width:900px;margin:auto;padding:22px}nav{display:flex;gap:18px;margin-bottom:22px}nav a{color:#176b51;font-weight:700;text-decoration:none}.bar{display:flex;gap:8px;margin-bottom:16px}.bar input{padding:9px;border:1px solid #ccd7cf;border-radius:7px}.bar button,.export,.action{border:0;border-radius:7px;padding:9px 12px;background:#176b51;color:white;font-weight:700;text-decoration:none}.order{background:#fff;border:1px solid #e2e7e2;border-radius:10px;margin:12px 0;padding:15px}.top{display:flex;justify-content:space-between;gap:8px}.muted{color:#66736a;font-size:12px;margin:4px 0}.items{margin:12px 0 0;padding-top:8px;border-top:1px solid #edf0ed}.item{display:flex;justify-content:space-between;padding:4px 0}@media(max-width:500px){main{padding:14px}.bar{flex-wrap:wrap}.bar input{min-width:0;flex:1}.top{display:block}}</style><main>{{template "nav" .}}<h1>Orders</h1><form class="bar"><input name="q" placeholder="Shop, mobile, order number" value="{{.Query}}"><input type="date" name="date" value="{{.Date}}"><button>Search</button><a class="export" href="/admin/orders.csv?q={{.Query}}&date={{.Date}}">Export CSV</a></form>{{if .Orders}}{{range .Orders}}<section class="order"><div class="top"><div><b>{{.Number}}</b><div class="muted">{{date .CreatedAt}} · {{.Shop.StoreName}} · {{.Shop.Mobile}}</div></div><b>₹{{money .Total}}</b></div><div>{{.Shop.CustomerName}}{{if .Shop.Address}} · {{.Shop.Address}}{{end}}{{if .Shop.Latitude}} · <a href="{{mapURL .Shop}}" target="_blank">Map</a>{{end}}</div><div class="items">{{range .Items}}<div class="item"><span>{{.Name}} <small>({{.SKU}})</small></span><span>{{.Quantity}} {{.Unit}} × ₹{{money .Rate}} = ₹{{money .LineTotal}}</span></div>{{end}}</div>{{if .Notes}}<p class="muted">Note: {{.Notes}}</p>{{end}}</section>{{end}}{{else}}<p>No matching orders yet.</p>{{end}}</main>`
const productsTemplate = `<!doctype html><title>Products · Ordex admin</title><style>body{font:14px system-ui;margin:0;background:#f5f7f5;color:#17221e}main{max-width:900px;margin:auto;padding:22px}nav{display:flex;gap:18px;margin-bottom:22px}nav a,.edit,.import{color:#176b51;font-weight:700;text-decoration:none}.add{background:#176b51;color:#fff;padding:9px 12px;border-radius:7px;text-decoration:none;font-weight:700}.import{margin-left:12px}.row{background:#fff;border:1px solid #e2e7e2;border-radius:9px;margin:8px 0;padding:12px;display:flex;justify-content:space-between;gap:10px}.muted{color:#66736a;font-size:12px;margin-top:3px}.inactive{opacity:.5}@media(max-width:500px){main{padding:14px}.row{display:block}.edit{display:inline-block;margin-top:8px}}</style><main>{{template "nav" .}}<p><a class="add" href="/admin/products/new">Add product</a><a class="import" href="/admin/products/import">Import CSV</a></p>{{range .Products}}<div class="row {{if not .Active}}inactive{{end}}"><div><b>{{if .SimpleName}}{{.SimpleName}}{{else}}{{.Name}}{{end}}</b><div class="muted">ERP: {{.Name}} · {{.SKU}} · {{.Company}} / {{.Brand}} · {{.Packing}} · ₹{{money .Rate}}/{{.Unit}}{{if not .Active}} · Inactive{{end}}</div></div><a class="edit" href="/admin/products/{{.ID}}/edit">Edit</a></div>{{else}}<p>No products.</p>{{end}}</main>`
const productTemplate = `<!doctype html><title>Product · Ordex admin</title><style>body{font:14px system-ui;margin:0;background:#f5f7f5;color:#17221e}main{max-width:620px;margin:auto;padding:22px}nav{display:flex;gap:18px;margin-bottom:22px}nav a{color:#176b51;font-weight:700;text-decoration:none}form{background:#fff;border:1px solid #e2e7e2;border-radius:10px;padding:17px;display:grid;gap:12px}label{display:grid;gap:5px;font-weight:650}input{border:1px solid #ccd7cf;border-radius:7px;padding:10px;font:inherit}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.save,.delete{border:0;border-radius:7px;padding:11px;background:#176b51;color:#fff;font-weight:700}.delete{background:#b2402b;margin-top:12px}.error{color:#b2402b}small{font-weight:500;color:#66736a}</style><main>{{template "nav" .}}<h1>{{if .Product.ID}}Edit{{else}}Add{{end}} product</h1>{{if .Error}}<p class="error">{{.Error}}</p>{{end}}<form method="post" action="{{if .Product.ID}}/admin/products/{{.Product.ID}}{{else}}/admin/products{{end}}"><label>SKU<input name="sku" required value="{{.Product.SKU}}"></label><label>ERP product name<input name="name" required value="{{.Product.Name}}"></label><label>Simple name <small>Shown to shopkeepers; use clear everyday wording.</small><input name="simpleName" value="{{.Product.SimpleName}}"></label><div class="grid"><label>Company<input name="company" required value="{{.Product.Company}}"></label><label>Brand<input name="brand" required value="{{.Product.Brand}}"></label></div><div class="grid"><label>Category<input name="category" required value="{{.Product.Category}}"></label><label>Unit <small>case, box, piece</small><input name="unit" required value="{{.Product.Unit}}"></label></div><label>Packing<input name="packing" required value="{{.Product.Packing}}"></label><div class="grid"><label>Sale rate (₹)<input name="rate" inputmode="decimal" required value="{{money .Product.Rate}}"></label><label>MRP (₹)<input name="mrp" inputmode="decimal" required value="{{money .Product.MRP}}"></label></div><label>Image URL <small>optional</small><input name="imageUrl" value="{{.Product.ImageURL}}"></label><label><input type="checkbox" name="active"{{if .Active}} checked{{end}}> Active in catalogue</label><button class="save">Save product</button></form>{{if .Product.ID}}<form method="post" action="/admin/products/{{.Product.ID}}/delete" onsubmit="return confirm('Delete this product?')"><button class="delete">Delete product</button></form>{{end}}</main>`

const importTemplate = `<!doctype html><title>Import products · Ordex admin</title><style>body{font:14px system-ui;margin:0;background:#f5f7f5;color:#17221e}main{max-width:650px;margin:auto;padding:22px}nav{display:flex;gap:18px;margin-bottom:22px}nav a,a{color:#176b51;font-weight:700}form{display:grid;gap:14px;background:#fff;border:1px solid #e2e7e2;border-radius:10px;padding:18px}input{font:inherit}.submit{border:0;border-radius:7px;padding:11px;background:#176b51;color:#fff;font-weight:700}.error{color:#b2402b}.success{color:#176b51}.hint{color:#66736a;line-height:1.5}</style><main>{{template "nav" .}}<h1>Import products</h1><p class="hint">Download the template, fill one product per row, then upload it. Existing SKUs are updated; new SKUs are created. Rates are in rupees, for example <code>1788.00</code>.</p><p><a href="/admin/products/import-template.csv">Download CSV template</a></p>{{if .Error}}<p class="error">{{.Error}}</p>{{end}}{{if .Imported}}<p class="success">{{.Imported}} products imported successfully.</p>{{end}}<form method="post" action="/admin/products/import" enctype="multipart/form-data"><label>CSV file <input type="file" name="file" accept=".csv,text/csv" required></label><button class="submit">Import products</button></form></main>`
