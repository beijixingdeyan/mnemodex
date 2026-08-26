// Package store is a tiny in-process stand-in for a real datastore.
package store

import "sync"

// Pool is a thread-safe string map with a fixed capacity.
type Pool struct {
	mu    sync.Mutex
	items map[string]string
	limit int
}

// New creates a Pool capped at limit entries.
func New(limit int) *Pool {
	return &Pool{items: make(map[string]string, limit), limit: limit}
}

// Get returns the value for key, or "" if absent.
func (p *Pool) Get(key string) string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.items[key]
}