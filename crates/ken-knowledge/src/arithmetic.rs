//! A small exact rational evaluator. Grammar has no names, calls, or I/O.
use crate::{Result, invalid};
use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{One, Signed, ToPrimitive, Zero};
use serde_json::{Value, json};
#[derive(Clone)]
struct Rational {
    n: BigInt,
    d: BigInt,
}
impl Rational {
    fn new(mut n: BigInt, mut d: BigInt) -> Result<Self> {
        if d.is_zero() {
            return Err(invalid("Undefined or out-of-range arithmetic"));
        }
        if d.is_negative() {
            n = -n;
            d = -d;
        }
        let gcd = n.gcd(&d);
        n /= &gcd;
        d /= &gcd;
        if n.bits() > 2048 || d.bits() > 2048 {
            return Err(invalid("Arithmetic magnitude limit"));
        }
        Ok(Self { n, d })
    }
    fn binary(self, op: &str, r: Self) -> Result<Self> {
        match op {
            "+" => Self::new(&self.n * &r.d + &r.n * &self.d, &self.d * &r.d),
            "-" => Self::new(&self.n * &r.d - &r.n * &self.d, &self.d * &r.d),
            "*" => Self::new(self.n * r.n, self.d * r.d),
            "/" => Self::new(self.n * r.d, self.d * r.n),
            "**" => {
                if !r.d.is_one() || r.n.abs() > BigInt::from(16) {
                    return Err(invalid("Exponent must be an integer between -16 and 16"));
                }
                let exp = r.n.to_i32().unwrap();
                if exp < 0 {
                    Self::new(
                        self.d.pow(exp.unsigned_abs()),
                        self.n.pow(exp.unsigned_abs()),
                    )
                } else {
                    Self::new(self.n.pow(exp as u32), self.d.pow(exp as u32))
                }
            }
            _ => unreachable!(),
        }
    }
    fn number(token: &str) -> Result<Self> {
        if token.len() > 30 {
            return Err(invalid("Number too long"));
        }
        let token = token.replace('_', "");
        let (mantissa, exp) = if let Some(i) = token.find(['e', 'E']) {
            let exp = token[i + 1..]
                .parse::<i32>()
                .map_err(|_| invalid("Decimal exponent magnitude limit"))?;
            if exp.unsigned_abs() > 100 {
                return Err(invalid("Decimal exponent magnitude limit"));
            }
            (&token[..i], exp)
        } else {
            (token.as_str(), 0)
        };
        let (digits, places) = if let Some(i) = mantissa.find('.') {
            (mantissa.replace('.', ""), (mantissa.len() - i - 1) as i32)
        } else {
            (mantissa.to_owned(), 0)
        };
        let n = digits
            .parse::<BigInt>()
            .map_err(|_| invalid("Invalid arithmetic expression"))?;
        let scale = places - exp;
        if scale >= 0 {
            Self::new(n, BigInt::from(10).pow(scale as u32))
        } else {
            Self::new(n * BigInt::from(10).pow((-scale) as u32), BigInt::one())
        }
    }
    fn exact(&self) -> String {
        if self.d.is_one() {
            self.n.to_string()
        } else {
            format!("{}/{}", self.n, self.d)
        }
    }
}
struct Parser<'a> {
    source: &'a str,
    pos: usize,
    nodes: usize,
    depth: usize,
}
impl Parser<'_> {
    fn skip(&mut self) {
        while self
            .source
            .as_bytes()
            .get(self.pos)
            .is_some_and(u8::is_ascii_whitespace)
        {
            self.pos += 1;
        }
    }
    fn consume(&mut self, token: &str) -> bool {
        self.skip();
        if self.source[self.pos..].starts_with(token) {
            self.pos += token.len();
            true
        } else {
            false
        }
    }
    fn count(&mut self, n: usize) -> Result<()> {
        self.nodes += n;
        if self.nodes > 100 {
            return Err(invalid("Expression too complex"));
        }
        Ok(())
    }
    fn sum(&mut self) -> Result<Rational> {
        let mut x = self.product()?;
        loop {
            let op = if self.consume("+") {
                "+"
            } else if self.consume("-") {
                "-"
            } else {
                break;
            };
            self.count(2)?;
            x = x.binary(op, self.product()?)?;
        }
        Ok(x)
    }
    fn product(&mut self) -> Result<Rational> {
        let mut x = self.factor()?;
        loop {
            self.skip();
            if self.source[self.pos..].starts_with("**") {
                break;
            }
            let op = if self.consume("*") {
                "*"
            } else if self.consume("/") {
                "/"
            } else {
                break;
            };
            self.count(2)?;
            x = x.binary(op, self.factor()?)?;
        }
        Ok(x)
    }
    fn factor(&mut self) -> Result<Rational> {
        self.depth += 1;
        if self.depth > 100 {
            return Err(invalid("Expression too complex"));
        }
        let x = if self.consume("+") {
            self.count(2)?;
            self.factor()?
        } else if self.consume("-") {
            self.count(2)?;
            let mut x = self.factor()?;
            x.n = -x.n;
            x
        } else {
            self.power()?
        };
        self.depth -= 1;
        Ok(x)
    }
    fn power(&mut self) -> Result<Rational> {
        let x = self.atom()?;
        if self.consume("**") {
            self.count(2)?;
            x.binary("**", self.factor()?)
        } else {
            Ok(x)
        }
    }
    fn atom(&mut self) -> Result<Rational> {
        if self.consume("(") {
            let x = self.sum()?;
            if !self.consume(")") {
                return Err(invalid("Invalid arithmetic expression"));
            }
            return Ok(x);
        }
        self.skip();
        let start = self.pos;
        let bytes = self.source.as_bytes();
        let mut digits = 0;
        while bytes
            .get(self.pos)
            .is_some_and(|b| b.is_ascii_digit() || *b == b'_')
        {
            if bytes[self.pos].is_ascii_digit() {
                digits += 1;
            }
            self.pos += 1;
        }
        if bytes.get(self.pos) == Some(&b'.') {
            self.pos += 1;
            while bytes
                .get(self.pos)
                .is_some_and(|b| b.is_ascii_digit() || *b == b'_')
            {
                if bytes[self.pos].is_ascii_digit() {
                    digits += 1;
                }
                self.pos += 1;
            }
        }
        if digits == 0 {
            return Err(invalid(
                "Only numbers, parentheses and + - * / ** are supported",
            ));
        }
        if bytes
            .get(self.pos)
            .is_some_and(|b| *b == b'e' || *b == b'E')
        {
            self.pos += 1;
            if bytes
                .get(self.pos)
                .is_some_and(|b| *b == b'+' || *b == b'-')
            {
                self.pos += 1;
            }
            let exp_start = self.pos;
            while bytes
                .get(self.pos)
                .is_some_and(|b| b.is_ascii_digit() || *b == b'_')
            {
                self.pos += 1;
            }
            if self.pos == exp_start {
                return Err(invalid("Invalid arithmetic expression"));
            }
        }
        let token = &self.source[start..self.pos];
        if token.starts_with('_')
            || token.ends_with('_')
            || token.contains("__")
            || token.contains("_.")
            || token.contains("._")
            || token.contains("_e")
            || token.contains("_E")
            || token.contains("e_")
            || token.contains("E_")
        {
            return Err(invalid("Invalid arithmetic expression"));
        }
        self.count(1)?;
        Rational::number(token)
    }
}
pub fn calculate(expression: &str) -> Result<Value> {
    if expression.trim().is_empty() || expression.chars().count() > 400 {
        return Err(invalid("Arithmetic expression: 1..400 characters"));
    }
    if !expression.is_ascii() {
        return Err(invalid("Invalid arithmetic expression"));
    }
    let mut parser = Parser {
        source: expression,
        pos: 0,
        nodes: 1,
        depth: 0,
    };
    let result = parser.sum()?;
    parser.skip();
    if parser.pos != expression.len() {
        return Err(invalid(
            "Only numbers, parentheses and + - * / ** are supported",
        ));
    }
    Ok(
        json!({"status":"calculated","expression":expression,"exact":result.exact(),"method":"rational-arithmetic/1","stored_as_premise":false}),
    )
}
