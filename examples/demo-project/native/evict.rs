//! Clock-ish LRU eviction, mirroring the Python `TokenCache` policy:
//! when over capacity, the oldest slot is dropped first.

/// Truncates `keys` to at most `max` entries, removing from the front.
pub fn evict_lru(keys: &mut Vec<String>, max: usize) {
    if keys.len() <= max {
        return;
    }
    keys.drain(..keys.len() - max);
}

#[cfg(test)]
mod tests {
    #[test]
    fn evicts_oldest_first() {
        let mut keys = vec!["a".into(), "b".into(), "c".into()];
        super::evict_lru(&mut keys, 2);
        assert_eq!(keys, vec!["b".into(), "c".into()]);
    }
}