use super::*;
use context::*;
use ken_program::Operation;
impl Context<'_> {
    pub fn insert_match(
        &mut self,
        item: &Clause,
        operation: &Operation,
        current: &Bindings,
        updated: &mut Bindings,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let mut subjects = vec![operation.id.clone()];
        if let Some(call) = self.call(operation) {
            subjects.push(call.id.clone());
        }
        let mut collections = BTreeSet::new();
        for subject in &subjects {
            collections.extend(self.ids("INSERTS_INTO", subject, s)?);
            collections.extend(self.ids("WRITES_ELEMENT", subject, s)?);
        }
        let collection = if let Some(collection) = node(current, &item.role) {
            collection
        } else {
            let mut options = collections.clone();
            for bucket in &collections {
                options.extend(self.ids("CONTAINER", bucket, s)?);
            }
            if options.len() != 1 {
                return Ok(truth(false));
            }
            let value = self.value_node(options.into_iter().next().unwrap(), "STORAGE");
            let Value::Node(collection) = value else {
                unreachable!()
            };
            updated.insert(item.role.clone(), Value::Node(collection.clone()));
            collection
        };
        if !item.name.is_empty() {
            let counts = self.rows("INDEXED_WRITE_COUNT", Some(&operation.id), None, s)?;
            if counts.len() != 1 || counts[0].object != item.name {
                return Ok(truth(false));
            }
        }
        let landed = self.landed_place(Some(&Value::Node(collection.clone())), s)?;
        let collection = if !landed.is_empty() && collections.contains(&landed) {
            let Value::Node(n) = self.value_node(landed, "STORAGE") else {
                unreachable!()
            };
            n
        } else {
            collection
        };
        let mut key_verified = false;
        if !collections.contains(&collection.local_id) {
            let mut matched = false;
            for bucket in &collections {
                if !self.has("CONTAINER", bucket, &collection.local_id, s)? {
                    continue;
                }
                if item.expressions.len() > 1 {
                    let expected = op(item, 1)?;
                    let Some(key) =
                        node(current, expected.value()).filter(|_| expected.kind() == "role")
                    else {
                        continue;
                    };
                    if !self.has("INDEX", bucket, &key.local_id, s)? {
                        continue;
                    }
                }
                matched = true;
                key_verified = item.expressions.len() > 1;
                break;
            }
            if !matched {
                return Ok(truth(false));
            }
        }
        let mut values = BTreeSet::new();
        let mut inserted = BTreeSet::new();
        let mut inputs = BTreeSet::new();
        let mut arguments = BTreeSet::new();
        for subject in &subjects {
            values.extend(self.ids("INSERTED_VALUE", subject, s)?);
            inserted.extend(self.ids("STORES_VALUE", subject, s)?);
            inserted.extend(self.ids("ASSIGNMENT_VALUE", subject, s)?);
            inputs.extend(self.ids("INSERTED_INPUT", subject, s)?);
            arguments.extend(self.ids("ARGUMENT", subject, s)?);
        }
        inserted.extend(values.iter().cloned());
        if !inputs.is_empty() {
            inserted = inserted.intersection(&inputs).cloned().collect();
        }
        let mut carried = inserted.clone();
        let mut frontier = inserted;
        for _ in 0..3 {
            s.check()?;
            let mut following = BTreeSet::new();
            for value in frontier {
                for relation in ["ASSIGNED_FROM", "FLOWS_TO", "ARGUMENT"] {
                    following.extend(self.ids(relation, &value, s)?);
                }
            }
            following = following.difference(&carried).cloned().collect();
            if following.is_empty() {
                break;
            }
            carried.extend(following.iter().cloned());
            frontier = following;
        }
        let expected = op(item, 0)?;
        let mut result = self.source_matches(
            expected,
            operation,
            updated,
            if carried.is_empty() {
                None
            } else {
                Some(carried)
            },
            s,
        )?;
        if result.is_false() && expected.kind() == "role" {
            let operand = current.get(expected.value());
            let landing = self.landed_place(operand, s)?;
            if !landing.is_empty()
                && (values.contains(&landing) || arguments.contains(&landing))
                && let Some(Value::Node(operand)) = operand
            {
                let producer = self.producers.get(&operand.local_id).cloned();
                let other = self
                    .rows("ASSIGNED_FROM", Some(&landing), None, s)?
                    .into_iter()
                    .filter(|f| Some(&f.object) != producer.as_ref())
                    .map(|f| f.object.clone())
                    .collect::<Vec<_>>();
                let mut safe = true;
                for place in other {
                    if place.contains("/COLLECTION:")
                        || !self
                            .rows("ALLOCATES_TYPE", Some(&place), None, s)?
                            .is_empty()
                    {
                        continue;
                    }
                    let metadata = self.rows("ENTITY", Some(&place), None, s)?;
                    if !metadata
                        .iter()
                        .any(|f| attr(&f.attrs, "construction").is_ok_and(|v| v.truthy()))
                    {
                        safe = false;
                        break;
                    }
                }
                if safe {
                    result = truth(true);
                }
            }
        }
        if !result.is_false()
            && inputs.is_empty()
            && !values.is_empty()
            && item.expressions.len() == 1
            && let Some(operand) = node(current, expected.value())
            && (operand.kind == "PARAMETER"
                || self.has("ENTITY", &operand.local_id, "PARAMETER", s)?)
        {
            result = truth(false);
        }
        if !result.is_false() && item.expressions.len() > 1 && !key_verified {
            let mut keys = BTreeSet::new();
            for subject in subjects {
                keys.extend(self.ids("INDEX", &subject, s)?);
            }
            result = result.and(self.source_matches(
                op(item, 1)?,
                operation,
                updated,
                if keys.is_empty() { None } else { Some(keys) },
                s,
            )?);
        }
        Ok(result)
    }
}
