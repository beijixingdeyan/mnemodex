// cmd/server.go — demo tracker service entry point.
package main

import (
	"fmt"
	"sync"
)

// Tracker keeps seen IDs in memory; safe for concurrent use.
type Tracker struct {
	mu   sync.Mutex
	seen map[string]bool
	cap  int
}

// NewTracker returns a Tracker that keeps at most capacity IDs.
func NewTracker(capacity int) *Tracker {
	return &Tracker{seen: make(map[string]bool, capacity), cap: capacity}
}

// Track records id, evicting the oldest entry when at capacity
// (clock-ish policy, mirroring service/cache.py).
func (t *Tracker) Track(id string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if len(t.seen) >= t.cap {
		for old := range t.seen {
			delete(t.seen, old)
			break
		}
	}
	t.seen[id] = true
}

func main() {
	t := NewTracker(128)
	t.Track("demo")
	fmt.Println("tracked:", len(t.seen))
}