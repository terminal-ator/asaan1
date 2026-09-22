package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	_ "modernc.org/sqlite"
)

const schema = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    simple_name TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    packing TEXT NOT NULL,
    unit TEXT NOT NULL,
    rate INTEGER NOT NULL,
    mrp INTEGER NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    updated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL UNIQUE,
    order_number TEXT NOT NULL UNIQUE,
    shop_json TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    rate INTEGER NOT NULL,
    line_total INTEGER NOT NULL
);`

type Product struct {
	ID         string `json:"id"`
	SKU        string `json:"sku"`
	Name       string `json:"name"`
	SimpleName string `json:"simpleName,omitempty"`
	Company    string `json:"company"`
	Brand      string `json:"brand"`
	Category   string `json:"category"`
	Packing    string `json:"packing"`
	Unit       string `json:"unit"`
	Rate       int64  `json:"rate"` // paise
	MRP        int64  `json:"mrp"`  // paise
	ImageURL   string `json:"imageUrl,omitempty"`
	UpdatedAt  string `json:"updatedAt"`
	CreatedAt  string `json:"createdAt"`
}

// The app saves its shop profile and history locally. A shop snapshot is sent
// with each order so that an exported order remains meaningful on its own.
type Shop struct {
	StoreName        string  `json:"storeName" binding:"required"`
	CustomerName     string  `json:"customerName,omitempty"`
	Mobile           string  `json:"mobile" binding:"required"`
	GSTIN            string  `json:"gstin,omitempty"`
	Address          string  `json:"address,omitempty"`
	Latitude         float64 `json:"latitude,omitempty"`
	Longitude        float64 `json:"longitude,omitempty"`
	LocationAccuracy float64 `json:"locationAccuracy,omitempty"`
}

type OrderItem struct {
	ProductID string `json:"productId"`
	LegacyID  string `json:"id"` // accepts orders queued by the first PWA build
	SKU       string `json:"sku" binding:"required"`
	Name      string `json:"name" binding:"required"`
	Unit      string `json:"unit" binding:"required"`
	Quantity  int64  `json:"quantity" binding:"required,gt=0"`
	Rate      int64  `json:"rate" binding:"gte=0"` // snapshot, in paise
}

type CreateOrderRequest struct {
	ClientOrderID string      `json:"clientOrderId" binding:"required"`
	Shop          Shop        `json:"shop" binding:"required"`
	Items         []OrderItem `json:"items" binding:"required,min=1,dive"`
	Notes         string      `json:"notes,omitempty"`
}

func main() {
	if err := validateProductionConfig(); err != nil {
		log.Fatal(err)
	}
	db, err := openDatabase()
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery(), securityHeaders(), cors())
	r.Static("/uploads", productImageDir())
	r.GET("/health", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"ok": true}) })
	r.GET("/api/catalogue", catalogue(db))
	r.POST("/api/orders", createOrder(db))
	r.GET("/admin/login", adminLoginPage())
	r.POST("/admin/login", adminLogin())
	r.POST("/admin/logout", adminLogout())
	r.GET("/admin", adminAuth(), adminDashboard(db))
	r.GET("/admin/orders.csv", adminAuth(), exportOrders(db))
	r.GET("/admin/products", adminAuth(), productList(db))
	r.GET("/admin/products/new", adminAuth(), productForm(db, nil))
	r.GET("/admin/products/import", adminAuth(), productImportPage())
	r.GET("/admin/products/import-template.csv", adminAuth(), productImportTemplate())
	r.POST("/admin/products/import", adminAuth(), importProducts(db))
	r.POST("/admin/products", adminAuth(), saveProduct(db, false))
	r.GET("/admin/products/:id/edit", adminAuth(), editProduct(db))
	r.POST("/admin/products/:id", adminAuth(), saveProduct(db, true))
	r.POST("/admin/products/:id/delete", adminAuth(), deleteProduct(db))

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("ordex API listening on :%s", port)
	log.Fatal(r.Run(":" + port))
}

func openDatabase() (*sql.DB, error) {
	path := os.Getenv("DATABASE_PATH")
	if path == "" {
		path = "ordex.db"
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	if _, err = db.Exec(schema); err != nil {
		db.Close()
		return nil, err
	}
	if _, err = db.Exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;`); err != nil {
		db.Close()
		return nil, err
	}
	// Existing local databases predate created_at; preserve their original
	// timestamps when bringing them forward.
	if _, err = db.Exec(`ALTER TABLE products ADD COLUMN created_at DATETIME`); err != nil && !strings.Contains(err.Error(), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err = db.Exec(`ALTER TABLE products ADD COLUMN simple_name TEXT NOT NULL DEFAULT ''`); err != nil && !strings.Contains(err.Error(), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err = db.Exec(`UPDATE products SET created_at = updated_at WHERE created_at IS NULL`); err != nil {
		db.Close()
		return nil, err
	}
	return db, seedProducts(db)
}

func catalogue(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		rows, err := db.QueryContext(c, `SELECT id, sku, name, simple_name, company, brand, category, packing, unit, rate, mrp, image_url, updated_at, created_at FROM products WHERE active = 1 ORDER BY company, brand, name`)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not load catalogue"})
			return
		}
		defer rows.Close()

		products := make([]Product, 0)
		for rows.Next() {
			var p Product
			var updated, created time.Time
			if err := rows.Scan(&p.ID, &p.SKU, &p.Name, &p.SimpleName, &p.Company, &p.Brand, &p.Category, &p.Packing, &p.Unit, &p.Rate, &p.MRP, &p.ImageURL, &updated, &created); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "could not read catalogue"})
				return
			}
			p.UpdatedAt = updated.UTC().Format(time.RFC3339)
			p.CreatedAt = created.UTC().Format(time.RFC3339)
			products = append(products, p)
		}
		c.JSON(http.StatusOK, gin.H{"products": products, "updatedAt": time.Now().UTC().Format(time.RFC3339)})
	}
}

func createOrder(db *sql.DB) gin.HandlerFunc {
	return func(c *gin.Context) {
		var input CreateOrderRequest
		if err := c.ShouldBindJSON(&input); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "shop, clientOrderId, and at least one valid item are required"})
			return
		}
		for i := range input.Items {
			if input.Items[i].ProductID == "" {
				input.Items[i].ProductID = input.Items[i].LegacyID
			}
			if input.Items[i].ProductID == "" {
				c.JSON(http.StatusBadRequest, gin.H{"error": "every item needs a product ID"})
				return
			}
		}

		tx, err := db.BeginTx(c, nil)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not save order"})
			return
		}
		defer tx.Rollback()

		var existing string
		err = tx.QueryRowContext(c, "SELECT order_number FROM orders WHERE client_order_id = ?", input.ClientOrderID).Scan(&existing)
		if err == nil {
			c.JSON(http.StatusOK, gin.H{"orderNumber": existing, "duplicate": true})
			return
		}
		if !errors.Is(err, sql.ErrNoRows) {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not save order"})
			return
		}

		total := int64(0)
		for i := range input.Items {
			item := &input.Items[i]
			var productUnit string
			if err := tx.QueryRowContext(c, `SELECT sku, name, unit, rate FROM products WHERE id = ? AND active = 1`, item.ProductID).Scan(&item.SKU, &item.Name, &productUnit, &item.Rate); err != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": "one or more products are unavailable"})
				return
			}
			if item.Unit != productUnit {
				c.JSON(http.StatusBadRequest, gin.H{"error": "one or more product units are invalid"})
				return
			}
			total += item.Quantity * item.Rate
		}
		orderID := uuid.NewString()
		orderNumber := "ORD-" + time.Now().UTC().Format("20060102-150405") + "-" + strings.ToUpper(uuid.NewString()[:4])
		shopJSON, _ := json.Marshal(input.Shop)
		if _, err = tx.ExecContext(c, `INSERT INTO orders (id, client_order_id, order_number, shop_json, notes, total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`, orderID, input.ClientOrderID, orderNumber, shopJSON, input.Notes, total, time.Now().UTC()); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not save order"})
			return
		}
		for _, item := range input.Items {
			if _, err = tx.ExecContext(c, `INSERT INTO order_items (id, order_id, product_id, sku, name, unit, quantity, rate, line_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, uuid.NewString(), orderID, item.ProductID, item.SKU, item.Name, item.Unit, item.Quantity, item.Rate, item.Quantity*item.Rate); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "could not save order"})
				return
			}
		}
		if err = tx.Commit(); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "could not save order"})
			return
		}
		c.JSON(http.StatusCreated, gin.H{"orderNumber": orderNumber, "total": total, "duplicate": false})
	}
}

func cors() gin.HandlerFunc {
	allowed := map[string]bool{}
	origins := os.Getenv("ALLOWED_ORIGINS")
	if origins == "" {
		origins = "http://localhost:5173,http://127.0.0.1:5173"
	}
	for _, origin := range strings.Split(origins, ",") {
		allowed[strings.TrimSpace(origin)] = true
	}
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if origin != "" && allowed[origin] {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Vary", "Origin")
		}
		c.Header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type")
		if c.Request.Method == http.MethodOptions {
			c.Status(http.StatusNoContent)
			c.Abort()
			return
		}
		c.Next()
	}
}

func securityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Header("Referrer-Policy", "strict-origin-when-cross-origin")
		c.Next()
	}
}

func validateProductionConfig() error {
	if os.Getenv("APP_ENV") != "production" {
		return nil
	}
	if os.Getenv("ADMIN_PASSWORD") == "" || os.Getenv("ADMIN_SESSION_SECRET") == "" {
		return errors.New("ADMIN_PASSWORD and ADMIN_SESSION_SECRET are required in production")
	}
	if os.Getenv("ALLOWED_ORIGINS") == "" {
		return errors.New("ALLOWED_ORIGINS is required in production")
	}
	return nil
}

func seedProducts(db *sql.DB) error {
	var count int
	if err := db.QueryRow("SELECT COUNT(*) FROM products").Scan(&count); err != nil || count > 0 {
		return err
	}
	now := time.Now().UTC()
	_, err := db.Exec(`INSERT INTO products (id, sku, name, simple_name, company, brand, category, packing, unit, rate, mrp, active, updated_at, created_at) VALUES
		('prd_surf_1kg', 'SURF-1KG-12', 'Surf Excel Easy Wash 1 kg', 'Surf Excel 1 kg', 'HUL', 'Surf Excel', 'Detergent', '1 kg × 12', 'case', 178800, 216000, 1, ?, ?),
		('prd_coke_750', 'COKE-750-24', 'Coca-Cola 750 ml', 'Coke 750 ml', 'Coca-Cola', 'Coca-Cola', 'Beverages', '750 ml × 24', 'case', 84000, 96000, 1, ?, ?),
		('prd_clinic_175', 'CLINIC-175-48', 'Clinic Plus Shampoo 175 ml', 'Clinic Plus 175 ml', 'HUL', 'Clinic Plus', 'Personal Care', '175 ml × 48', 'case', 336000, 408000, 1, ?, ?)`, now, now, now, now, now, now)
	return err
}
