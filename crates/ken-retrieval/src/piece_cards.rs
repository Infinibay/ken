//! The fixed model-input projection of authenticated requested source pieces.
use crate::{
    EntityKey, Span,
    query::CodeMatch,
    source_catalog::{PieceIdentity, SourceCatalog, entity_id},
    source_locator::module_name,
    source_snapshot::{SourceError, SourceResult, invalid},
};
use ken_text::{PythonText, unicode};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const CARD_PROJECTION: &str = "requested-piece-card-v102";
const MAX_LINES: usize = 64;
const MAX_EXCERPTS: usize = 4;
const MAX_CHARS: usize = 12000;

/// An owner identity relative to the physical path carried by its unit/excerpt.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CardEntity {
    pub kind: String,
    pub qualname: Option<String>,
    pub owner: Option<String>,
    pub definition_ordinal: usize,
}
impl From<&EntityKey> for CardEntity {
    fn from(key: &EntityKey) -> Self {
        Self {
            kind: key.kind.clone(),
            qualname: key.qualname.clone(),
            owner: key.owner.clone(),
            definition_ordinal: key.definition_ordinal,
        }
    }
}
impl CardEntity {
    pub(crate) fn at(&self, path: &str) -> EntityKey {
        EntityKey {
            path: path.into(),
            kind: self.kind.clone(),
            qualname: self.qualname.clone(),
            owner: self.owner.clone(),
            definition_ordinal: self.definition_ordinal,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PieceUnit {
    pub target_kind: String,
    pub path: String,
    pub entity: Option<CardEntity>,
    pub module_name: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PieceExcerpt {
    pub role: String,
    pub path: String,
    pub start_line: usize,
    pub end_line: usize,
    pub source_hash: String,
    pub entity: Option<CardEntity>,
    pub content: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PieceCard {
    pub unit: PieceUnit,
    pub source_hash: String,
    pub excerpts: Vec<PieceExcerpt>,
    pub truncated: bool,
}
/// Scalar physical source uses Python's compact sorted-key JSON character budget.
pub fn canonical_card(card: &PieceCard) -> String {
    serde_json::to_string(&serde_json::to_value(card).expect("scalar source card"))
        .expect("scalar source card")
}
pub fn card_text(card: &PieceCard) -> String {
    let unit = &card.unit;
    let name = unit
        .entity
        .as_ref()
        .and_then(|e| e.qualname.as_deref())
        .filter(|s| !s.is_empty())
        .or(unit.module_name.as_deref())
        .unwrap_or("");
    let mut text = format!("{} {} {}\n", unit.target_kind, unit.path, name);
    for (index, excerpt) in card.excerpts.iter().enumerate() {
        if index > 0 {
            text.push('\n');
        }
        let owner = excerpt
            .entity
            .as_ref()
            .and_then(|e| e.qualname.as_deref())
            .filter(|s| !s.is_empty())
            .unwrap_or(&excerpt.path);
        text.push_str(&format!(
            "{} {} lines {}-{}:\n{}",
            excerpt.role, owner, excerpt.start_line, excerpt.end_line, excerpt.content
        ));
    }
    text
}
fn terms(text: &PythonText) -> BTreeSet<String> {
    let mut separated = String::new();
    let mut previous = None;
    for &point in text.codepoints() {
        let c = char::from_u32(point).unwrap_or('\0');
        if previous.is_some_and(|p: char| p.is_ascii_lowercase()) && c.is_ascii_uppercase() {
            separated.push(' ');
        }
        separated.push(c);
        previous = Some(c);
    }
    const STOP: &[&str] = &[
        "the", "and", "with", "that", "this", "from", "which", "what", "where", "class", "file",
        "module", "symbol", "function", "clase", "archivo", "modulo", "módulo", "simbolo",
        "símbolo", "función", "para", "que", "una", "los", "las", "del", "con",
    ];
    unicode::casefold(&separated)
        .split(|c| c == '_' || !unicode::word(c))
        .filter(|s| s.chars().count() >= 3 && !STOP.contains(s))
        .map(str::to_owned)
        .collect()
}
fn overlap(query: &BTreeSet<String>, text: &PythonText) -> usize {
    query.intersection(&terms(text)).count()
}
fn source_fit(
    catalog: &SourceCatalog,
    key: &EntityKey,
    query: &BTreeSet<String>,
) -> SourceResult<usize> {
    Ok(catalog
        .passages(key)?
        .iter()
        .map(|p| {
            let mut points = p.fields.body.codepoints().to_vec();
            points.push(32);
            points.extend(p.fields.documentation.codepoints());
            points.push(32);
            points.extend(key.qualname.as_deref().unwrap_or("").chars().map(u32::from));
            overlap(
                query,
                &PythonText::from_codepoints(points).expect("source points"),
            )
        })
        .max()
        .unwrap_or(0))
}
fn window(
    catalog: &SourceCatalog,
    key: &EntityKey,
    query: &BTreeSet<String>,
    width: usize,
    implementation: bool,
) -> SourceResult<Option<Span>> {
    let snapshot = &catalog.snapshots()[&key.path];
    let mut best: Option<(usize, usize, usize)> = None;
    for passage in catalog.passages(key)? {
        let start = if implementation {
            passage
                .span
                .start_line
                .max(passage.implementation_start_line.unwrap_or(0))
        } else {
            passage.span.start_line
        };
        let end = passage.span.end_line;
        if start > end {
            continue;
        }
        let width = width.min(end - start + 1);
        for a in start..=end - width + 1 {
            let b = a + width - 1;
            let score = overlap(
                query,
                &snapshot
                    .excerpt(Span {
                        start_line: a,
                        end_line: b,
                    })?
                    .into(),
            );
            if best
                .is_none_or(|(s, x, y)| score > s || (score == s && (a < x || (a == x && b > y))))
            {
                best = Some((score, a, b));
            }
        }
    }
    Ok(best.map(|(_, a, b)| Span {
        start_line: a,
        end_line: b,
    }))
}
struct Proposal<'a> {
    role: &'static str,
    key: &'a EntityKey,
    span: Span,
}
/// Accumulates new whole physical lines under the fixed projection's three budgets.
struct Projection {
    card: PieceCard,
    used: BTreeSet<usize>,
}
impl Projection {
    fn append(&mut self, proposal: &Proposal<'_>, catalog: &SourceCatalog) -> SourceResult<()> {
        if self.card.excerpts.len() >= MAX_EXCERPTS {
            return Ok(());
        }
        let mut runs: Vec<Span> = Vec::new();
        for line in proposal.span.start_line..=proposal.span.end_line {
            if self.used.contains(&line) {
                continue;
            }
            if let Some(last) = runs.last_mut().filter(|last| last.end_line + 1 == line) {
                last.end_line = line;
            } else {
                runs.push(Span {
                    start_line: line,
                    end_line: line,
                });
            }
        }
        let snapshot = &catalog.snapshots()[&self.card.unit.path];
        for span in runs {
            if self.used.len() >= MAX_LINES || self.card.excerpts.len() >= MAX_EXCERPTS {
                self.card.truncated = true;
                break;
            }
            let end = span
                .end_line
                .min(span.start_line + MAX_LINES - self.used.len() - 1);
            let excerpt = PieceExcerpt {
                role: proposal.role.into(),
                path: self.card.unit.path.clone(),
                start_line: span.start_line,
                end_line: end,
                source_hash: self.card.source_hash.clone(),
                entity: Some(proposal.key.into()),
                content: snapshot.excerpt(Span {
                    start_line: span.start_line,
                    end_line: end,
                })?,
            };
            self.card.excerpts.push(excerpt);
            while canonical_card(&self.card).chars().count() > MAX_CHARS {
                self.card.truncated = true;
                let excerpt = self.card.excerpts.last_mut().expect("new excerpt");
                if excerpt.end_line == excerpt.start_line {
                    self.card.excerpts.pop();
                    break;
                }
                excerpt.end_line -= 1;
                excerpt.content = snapshot.excerpt(Span {
                    start_line: excerpt.start_line,
                    end_line: excerpt.end_line,
                })?;
            }
            if let Some(excerpt) = self
                .card
                .excerpts
                .last()
                .filter(|e| e.start_line == span.start_line)
            {
                self.used.extend(excerpt.start_line..=excerpt.end_line);
            }
        }
        Ok(())
    }
}
pub fn build_card(
    primary: &PieceIdentity,
    kind: &str,
    supporting: &[EntityKey],
    query: &PythonText,
    catalog: &SourceCatalog,
) -> SourceResult<PieceCard> {
    let (path, entity) = match primary {
        PieceIdentity::Entity(key) => (key.path.as_str(), Some(key)),
        PieceIdentity::Path(path) => (path.as_str(), None),
    };
    let snapshot = catalog
        .snapshots()
        .get(path)
        .ok_or_else(|| invalid("unknown/stale card source"))?;
    let mut members = Vec::new();
    for key in &catalog.by_path()[path] {
        if entity.is_none()
            || entity == Some(key)
            || (kind == "class" && catalog.enclosing_class(key)? == entity)
        {
            members.push(key);
        }
    }
    let terms = terms(query);
    let mut ranked = Vec::new();
    for key in supporting {
        if let Some(member) = members.iter().copied().find(|m| *m == key)
            && !ranked.contains(&member)
        {
            ranked.push(member);
        }
    }
    let mut rest = members
        .iter()
        .copied()
        .filter(|key| !ranked.contains(key))
        .map(|key| Ok((key, source_fit(catalog, key, &terms)?, entity_id(key))))
        .collect::<SourceResult<Vec<_>>>()?;
    rest.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.2.cmp(&b.2)));
    ranked.extend(rest.into_iter().map(|(key, _, _)| key));
    let mut proposals = Vec::new();
    if let Some(key) = entity {
        let first = catalog
            .passages(key)?
            .iter()
            .min_by_key(|p| p.span.start_line)
            .expect("nonempty catalog owner");
        let start = first.span.start_line;
        let mut end = first.span.end_line.min(start + 11);
        if let Some(implementation) = first.implementation_start_line.filter(|i| *i > start) {
            end = end.min(implementation - 1);
        }
        proposals.push(Proposal {
            role: "declaration",
            key,
            span: Span {
                start_line: start,
                end_line: end,
            },
        });
    } else if let Some(key) = members
        .iter()
        .copied()
        .find(|key| key.kind == "module" && key.qualname.is_none())
        && let Some(span) = window(catalog, key, &terms, 12, false)?
    {
        proposals.push(Proposal {
            role: "documentation",
            key,
            span,
        });
    }
    let selected: Vec<_> = ranked
        .iter()
        .copied()
        .filter(|key| !(kind == "class" && entity == Some(*key) && ranked.len() > 1))
        .take(2)
        .collect();
    for (index, key) in selected.iter().enumerate() {
        if let Some(span) = window(catalog, key, &terms, if index == 0 { 36 } else { 16 }, true)? {
            proposals.push(Proposal {
                role: "implementation",
                key,
                span,
            });
        }
    }
    if proposals.len() < MAX_EXCERPTS
        && let Some(key) = selected.first()
    {
        let mut best = None;
        for passage in catalog.passages(key)? {
            if passage.fields.documentation.clone().trimmed().is_empty() {
                continue;
            }
            let score = overlap(&terms, &passage.fields.documentation);
            if best.as_ref().is_none_or(|(s, _)| score > *s) {
                best = Some((score, passage));
            }
        }
        if let Some((_, p)) = best {
            let start = p.span.start_line;
            let mut end = p.span.end_line.min(start + 11);
            if let Some(implementation) = p.implementation_start_line.filter(|i| *i > start) {
                end = end.min(implementation - 1);
            }
            proposals.push(Proposal {
                role: "documentation",
                key,
                span: Span {
                    start_line: start,
                    end_line: end,
                },
            });
        }
    }
    let mut projection = Projection {
        card: PieceCard {
            unit: PieceUnit {
                target_kind: kind.into(),
                path: path.into(),
                entity: entity.map(CardEntity::from),
                module_name: if kind == "module" {
                    module_name(path)
                } else {
                    None
                },
            },
            source_hash: snapshot.hash().into(),
            excerpts: Vec::new(),
            truncated: false,
        },
        used: BTreeSet::new(),
    };
    for proposal in &proposals {
        projection.append(proposal, catalog)?;
    }
    let [start, end] = if let Some(key) = entity {
        catalog.extent(key)?
    } else {
        [1, snapshot.lines().len()]
    };
    projection.card.truncated |= (start..=end).any(|line| !projection.used.contains(&line));
    validate_card(&projection.card, catalog, false)?;
    Ok(projection.card)
}
pub fn build_piece_cards(
    matches: &[CodeMatch],
    kind: &str,
    query: &PythonText,
    catalog: &SourceCatalog,
    limit: usize,
) -> SourceResult<Vec<PieceCard>> {
    let mut groups: Vec<(PieceIdentity, Vec<EntityKey>)> = Vec::new();
    for item in matches {
        catalog.admit_match(item)?;
        if let Some(primary) = catalog.primary(&item.entity, kind)? {
            if let Some((_, support)) = groups.iter_mut().find(|(key, _)| *key == primary) {
                support.push(item.entity.clone());
            } else {
                groups.push((primary, vec![item.entity.clone()]));
            }
        }
    }
    groups
        .iter()
        .take(limit)
        .map(|(primary, support)| build_card(primary, kind, support, query, catalog))
        .collect()
}
pub fn validate_card(
    card: &PieceCard,
    catalog: &SourceCatalog,
    check_disk: bool,
) -> SourceResult<()> {
    let unit = &card.unit;
    let path = &unit.path;
    let kind = unit.target_kind.as_str();
    let snapshot = catalog
        .snapshots()
        .get(path)
        .filter(|s| s.hash() == card.source_hash)
        .ok_or_else(|| invalid("unknown/stale card source"))?;
    if check_disk {
        let current = catalog.source().read(path).map_err(|error| match error {
            SourceError::Invalid(message) if message == "source outside root" => {
                invalid("source moved outside project root")
            }
            SourceError::Decode(_) => invalid("source changed since catalog"),
            other => other,
        })?;
        if current.hash() != card.source_hash {
            return Err(invalid("source changed since catalog"));
        }
    }
    let primary = if matches!(kind, "class" | "symbol") {
        let key = unit
            .entity
            .as_ref()
            .ok_or_else(|| invalid("wrong canonical piece type"))?
            .at(path);
        if catalog.passages(&key).is_err()
            || catalog.primary(&key, kind)? != Some(PieceIdentity::Entity(key.clone()))
        {
            return Err(invalid("wrong canonical piece type"));
        }
        Some(key)
    } else {
        if !matches!(kind, "file" | "module")
            || unit.entity.is_some()
            || (kind == "module" && module_name(path).is_none())
        {
            return Err(invalid("wrong physical/import unit"));
        }
        None
    };
    let mut count = 0usize;
    for excerpt in &card.excerpts {
        let key = if let Some(entity) = &excerpt.entity {
            entity.at(&excerpt.path)
        } else if matches!(kind, "file" | "module") {
            EntityKey {
                path: excerpt.path.clone(),
                kind: "module".into(),
                qualname: None,
                owner: None,
                definition_ordinal: 0,
            }
        } else {
            return Err(invalid("missing excerpt owner"));
        };
        let a = excerpt.start_line;
        let b = excerpt.end_line;
        if excerpt.path != *path
            || excerpt.source_hash != card.source_hash
            || catalog.passages(&key).is_err()
            || a == 0
            || a > b
            || b > snapshot.lines().len()
        {
            return Err(invalid("invalid excerpt provenance"));
        }
        if let Some(primary) = &primary
            && key != *primary
            && !(kind == "class" && catalog.enclosing_class(&key)? == Some(primary))
        {
            return Err(invalid("unrelated owner cannot support primary piece"));
        }
        let ranges = catalog.owned_ranges(&key, false)?;
        if !(a..=b).all(|line| {
            ranges
                .iter()
                .any(|[start, end]| *start <= line && line <= *end)
        }) {
            return Err(invalid("excerpt crosses source ownership"));
        }
        if excerpt.content
            != snapshot.excerpt(Span {
                start_line: a,
                end_line: b,
            })?
        {
            return Err(invalid("fabricated excerpt"));
        }
        count = count.saturating_add(b - a + 1);
    }
    if count > MAX_LINES
        || card.excerpts.len() > MAX_EXCERPTS
        || canonical_card(card).chars().count() > MAX_CHARS
    {
        return Err(invalid("card budget exceeded"));
    }
    Ok(())
}
