//! Generated from english.sbl by Snowball 3.0.1 - https://snowballstem.org/

use super::Among;
use super::SnowballEnv;

static A_0: &[Among<Context>; 8] = &[
    Among("arsen", -1, -1, None),
    Among("commun", -1, -1, None),
    Among("emerg", -1, -1, None),
    Among("gener", -1, -1, None),
    Among("later", -1, -1, None),
    Among("organ", -1, -1, None),
    Among("past", -1, -1, None),
    Among("univers", -1, -1, None),
];

static A_1: &[Among<Context>; 3] = &[
    Among("'", -1, 1, None),
    Among("'s'", 0, 1, None),
    Among("'s", -1, 1, None),
];

static A_2: &[Among<Context>; 6] = &[
    Among("ied", -1, 2, None),
    Among("s", -1, 3, None),
    Among("ies", 1, 2, None),
    Among("sses", 1, 1, None),
    Among("ss", 1, -1, None),
    Among("us", 1, -1, None),
];

static A_3: &[Among<Context>; 3] = &[
    Among("succ", -1, 1, None),
    Among("proc", -1, 1, None),
    Among("exc", -1, 1, None),
];

static A_4: &[Among<Context>; 7] = &[
    Among("even", -1, 2, None),
    Among("cann", -1, 2, None),
    Among("inn", -1, 2, None),
    Among("earr", -1, 2, None),
    Among("herr", -1, 2, None),
    Among("out", -1, 2, None),
    Among("y", -1, 1, None),
];

static A_5: &[Among<Context>; 7] = &[
    Among("", -1, -1, None),
    Among("ed", 0, 2, None),
    Among("eed", 1, 1, None),
    Among("ing", 0, 3, None),
    Among("edly", 0, 2, None),
    Among("eedly", 4, 1, None),
    Among("ingly", 0, 2, None),
];

static A_6: &[Among<Context>; 13] = &[
    Among("", -1, 3, None),
    Among("bb", 0, 2, None),
    Among("dd", 0, 2, None),
    Among("ff", 0, 2, None),
    Among("gg", 0, 2, None),
    Among("bl", 0, 1, None),
    Among("mm", 0, 2, None),
    Among("nn", 0, 2, None),
    Among("pp", 0, 2, None),
    Among("rr", 0, 2, None),
    Among("at", 0, 1, None),
    Among("tt", 0, 2, None),
    Among("iz", 0, 1, None),
];

static A_7: &[Among<Context>; 25] = &[
    Among("anci", -1, 3, None),
    Among("enci", -1, 2, None),
    Among("ogi", -1, 14, None),
    Among("li", -1, 16, None),
    Among("bli", 3, 12, None),
    Among("abli", 4, 4, None),
    Among("alli", 3, 8, None),
    Among("fulli", 3, 9, None),
    Among("lessli", 3, 15, None),
    Among("ousli", 3, 10, None),
    Among("entli", 3, 5, None),
    Among("aliti", -1, 8, None),
    Among("biliti", -1, 12, None),
    Among("iviti", -1, 11, None),
    Among("tional", -1, 1, None),
    Among("ational", 14, 7, None),
    Among("alism", -1, 8, None),
    Among("ation", -1, 7, None),
    Among("ization", 17, 6, None),
    Among("izer", -1, 6, None),
    Among("ator", -1, 7, None),
    Among("iveness", -1, 11, None),
    Among("fulness", -1, 9, None),
    Among("ousness", -1, 10, None),
    Among("ogist", -1, 13, None),
];

static A_8: &[Among<Context>; 9] = &[
    Among("icate", -1, 4, None),
    Among("ative", -1, 6, None),
    Among("alize", -1, 3, None),
    Among("iciti", -1, 4, None),
    Among("ical", -1, 4, None),
    Among("tional", -1, 1, None),
    Among("ational", 5, 2, None),
    Among("ful", -1, 5, None),
    Among("ness", -1, 5, None),
];

static A_9: &[Among<Context>; 18] = &[
    Among("ic", -1, 1, None),
    Among("ance", -1, 1, None),
    Among("ence", -1, 1, None),
    Among("able", -1, 1, None),
    Among("ible", -1, 1, None),
    Among("ate", -1, 1, None),
    Among("ive", -1, 1, None),
    Among("ize", -1, 1, None),
    Among("iti", -1, 1, None),
    Among("al", -1, 1, None),
    Among("ism", -1, 1, None),
    Among("ion", -1, 2, None),
    Among("er", -1, 1, None),
    Among("ous", -1, 1, None),
    Among("ant", -1, 1, None),
    Among("ent", -1, 1, None),
    Among("ment", 15, 1, None),
    Among("ement", 16, 1, None),
];

static A_10: &[Among<Context>; 2] = &[Among("e", -1, 1, None), Among("l", -1, 2, None)];

static A_11: &[Among<Context>; 14] = &[
    Among("andes", -1, -1, None),
    Among("atlas", -1, -1, None),
    Among("bias", -1, -1, None),
    Among("cosmos", -1, -1, None),
    Among("early", -1, 5, None),
    Among("gently", -1, 3, None),
    Among("howe", -1, -1, None),
    Among("idly", -1, 2, None),
    Among("news", -1, -1, None),
    Among("only", -1, 6, None),
    Among("singly", -1, 7, None),
    Among("skies", -1, 1, None),
    Among("sky", -1, -1, None),
    Among("ugly", -1, 4, None),
];

static G_AEO: &[u8; 2] = &[17, 64];

static G_V: &[u8; 4] = &[17, 65, 16, 1];

static G_V_WXY: &[u8; 5] = &[1, 17, 65, 208, 1];

static G_VALID_LI: &[u8; 3] = &[55, 141, 2];

#[derive(Clone)]
struct Context {
    b_y_found: bool,
    i_p2: i32,
    i_p1: i32,
}

fn r_prelude(env: &mut SnowballEnv, context: &mut Context) -> bool {
    context.b_y_found = false;
    let v_1 = env.cursor;
    'lab0: {
        env.bra = env.cursor;
        if !env.eq_s("'") {
            break 'lab0;
        }
        env.ket = env.cursor;
        if !env.slice_del() {
            return false;
        }
        break 'lab0;
    }
    env.cursor = v_1;
    let v_2 = env.cursor;
    'lab1: {
        env.bra = env.cursor;
        if !env.eq_s("y") {
            break 'lab1;
        }
        env.ket = env.cursor;
        if !env.slice_from("Y") {
            return false;
        }
        context.b_y_found = true;
        break 'lab1;
    }
    env.cursor = v_2;
    let v_3 = env.cursor;
    'lab2: {
        'replab3: loop {
            let v_4 = env.cursor;
            'lab4: {
                'golab5: loop {
                    let v_5 = env.cursor;
                    'lab6: {
                        if !env.in_grouping(G_V, 97, 121) {
                            break 'lab6;
                        }
                        env.bra = env.cursor;
                        if !env.eq_s("y") {
                            break 'lab6;
                        }
                        env.ket = env.cursor;
                        env.cursor = v_5;
                        break 'golab5;
                    }
                    env.cursor = v_5;
                    if env.cursor >= env.limit {
                        break 'lab4;
                    }
                    env.next_char();
                }
                if !env.slice_from("Y") {
                    return false;
                }
                context.b_y_found = true;
                continue 'replab3;
            }
            env.cursor = v_4;
            break 'replab3;
        }
        break 'lab2;
    }
    env.cursor = v_3;
    true
}

fn r_mark_regions(env: &mut SnowballEnv, context: &mut Context) -> bool {
    context.i_p1 = env.limit;
    context.i_p2 = env.limit;
    let v_1 = env.cursor;
    'lab0: {
        'lab1: {
            let v_2 = env.cursor;
            'lab2: {
                if env.cursor + 3 >= env.limit
                    || env.current.as_bytes()[(env.cursor + 3) as usize] >> 5 != 3_u8
                    || ((5513250_i32 >> (env.current.as_bytes()[(env.cursor + 3) as usize] & 0x1f))
                        & 1)
                        == 0
                {
                    break 'lab2;
                }

                if env.find_among(A_0, context) == 0 {
                    break 'lab2;
                }
                break 'lab1;
            }
            env.cursor = v_2;
            if !env.go_out_grouping(G_V, 97, 121) {
                break 'lab0;
            }
            env.next_char();
            if !env.go_in_grouping(G_V, 97, 121) {
                break 'lab0;
            }
            env.next_char();
            break 'lab1;
        }
        context.i_p1 = env.cursor;
        if !env.go_out_grouping(G_V, 97, 121) {
            break 'lab0;
        }
        env.next_char();
        if !env.go_in_grouping(G_V, 97, 121) {
            break 'lab0;
        }
        env.next_char();
        context.i_p2 = env.cursor;
        break 'lab0;
    }
    env.cursor = v_1;
    true
}

fn r_shortv(env: &mut SnowballEnv, _context: &mut Context) -> bool {
    'lab0: {
        let v_1 = env.limit - env.cursor;
        'lab1: {
            if !env.out_grouping_b(G_V_WXY, 89, 121) {
                break 'lab1;
            }
            if !env.in_grouping_b(G_V, 97, 121) {
                break 'lab1;
            }
            if !env.out_grouping_b(G_V, 97, 121) {
                break 'lab1;
            }
            break 'lab0;
        }
        env.cursor = env.limit - v_1;
        'lab2: {
            if !env.out_grouping_b(G_V, 97, 121) {
                break 'lab2;
            }
            if !env.in_grouping_b(G_V, 97, 121) {
                break 'lab2;
            }
            if env.cursor > env.limit_backward {
                break 'lab2;
            }
            break 'lab0;
        }
        env.cursor = env.limit - v_1;
        if !env.eq_s_b("past") {
            return false;
        }
        break 'lab0;
    }
    true
}

fn r_r1(env: &mut SnowballEnv, context: &mut Context) -> bool {
    context.i_p1 <= env.cursor
}

fn r_r2(env: &mut SnowballEnv, context: &mut Context) -> bool {
    context.i_p2 <= env.cursor
}

fn r_step_1a(env: &mut SnowballEnv, context: &mut Context) -> bool {
    let v_1 = env.limit - env.cursor;
    'lab0: {
        env.ket = env.cursor;
        if env.cursor <= env.limit_backward
            || (env.current.as_bytes()[(env.cursor - 1) as usize] != 39_u8
                && env.current.as_bytes()[(env.cursor - 1) as usize] != 115_u8)
        {
            env.cursor = env.limit - v_1;
            break 'lab0;
        }

        if env.find_among_b(A_1, context) == 0 {
            env.cursor = env.limit - v_1;
            break 'lab0;
        }
        env.bra = env.cursor;
        if !env.slice_del() {
            return false;
        }
        break 'lab0;
    }
    env.ket = env.cursor;
    if env.cursor <= env.limit_backward
        || (env.current.as_bytes()[(env.cursor - 1) as usize] != 100_u8
            && env.current.as_bytes()[(env.cursor - 1) as usize] != 115_u8)
    {
        return false;
    }

    let among_var = env.find_among_b(A_2, context);
    if among_var == 0 {
        return false;
    }
    env.bra = env.cursor;
    match among_var {
        1 if !env.slice_from("ss") => {
            return false;
        }
        2 => 'lab1: {
            let v_2 = env.limit - env.cursor;
            'lab2: {
                if !env.hop_back(2) {
                    break 'lab2;
                }
                if !env.slice_from("i") {
                    return false;
                }
                break 'lab1;
            }
            env.cursor = env.limit - v_2;
            if !env.slice_from("ie") {
                return false;
            }
            break 'lab1;
        }
        3 => {
            if env.cursor <= env.limit_backward {
                return false;
            }
            env.previous_char();
            if !env.go_out_grouping_b(G_V, 97, 121) {
                return false;
            }
            env.previous_char();
            if !env.slice_del() {
                return false;
            }
        }
        _ => (),
    }
    true
}

fn r_step_1b(env: &mut SnowballEnv, context: &mut Context) -> bool {
    let mut among_var;
    env.ket = env.cursor;
    if env.cursor - 1 <= env.limit_backward
        || env.current.as_bytes()[(env.cursor - 1) as usize] >> 5 != 3_u8
        || ((33554576_i32 >> (env.current.as_bytes()[(env.cursor - 1) as usize] & 0x1f)) & 1) == 0
    {
        among_var = -1;
    } else {
        among_var = env.find_among_b(A_5, context);
    }
    env.bra = env.cursor;
    'lab0: {
        let v_1 = env.limit - env.cursor;
        'lab1: {
            match among_var {
                1 => {
                    let v_2 = env.limit - env.cursor;
                    'lab2: {
                        'lab3: {
                            let v_3 = env.limit - env.cursor;
                            'lab4: {
                                if env.cursor - 2 <= env.limit_backward
                                    || env.current.as_bytes()[(env.cursor - 1) as usize] != 99_u8
                                {
                                    break 'lab4;
                                }

                                if env.find_among_b(A_3, context) == 0 {
                                    break 'lab4;
                                }
                                if env.cursor > env.limit_backward {
                                    break 'lab4;
                                }
                                break 'lab3;
                            }
                            env.cursor = env.limit - v_3;
                            if !r_r1(env, context) {
                                break 'lab2;
                            }
                            if !env.slice_from("ee") {
                                return false;
                            }
                            break 'lab3;
                        }
                        break 'lab2;
                    }
                    env.cursor = env.limit - v_2;
                }
                2 => {
                    break 'lab1;
                }
                3 => {
                    if env.cursor <= env.limit_backward
                        || env.current.as_bytes()[(env.cursor - 1) as usize] >> 5 != 3_u8
                        || ((34881536_i32
                            >> (env.current.as_bytes()[(env.cursor - 1) as usize] & 0x1f))
                            & 1)
                            == 0
                    {
                        break 'lab1;
                    }

                    among_var = env.find_among_b(A_4, context);
                    if among_var == 0 {
                        break 'lab1;
                    }
                    match among_var {
                        1 => {
                            let v_4 = env.limit - env.cursor;
                            if !env.out_grouping_b(G_V, 97, 121) {
                                break 'lab1;
                            }
                            if env.cursor > env.limit_backward {
                                break 'lab1;
                            }
                            env.cursor = env.limit - v_4;
                            env.bra = env.cursor;
                            if !env.slice_from("ie") {
                                return false;
                            }
                        }
                        2 if env.cursor > env.limit_backward => {
                            break 'lab1;
                        }
                        _ => (),
                    }
                }
                _ => (),
            }
            break 'lab0;
        }
        env.cursor = env.limit - v_1;
        let v_5 = env.limit - env.cursor;
        if !env.go_out_grouping_b(G_V, 97, 121) {
            return false;
        }
        env.previous_char();
        env.cursor = env.limit - v_5;
        if !env.slice_del() {
            return false;
        }
        env.ket = env.cursor;
        env.bra = env.cursor;
        let v_6 = env.limit - env.cursor;
        if env.cursor - 1 <= env.limit_backward
            || env.current.as_bytes()[(env.cursor - 1) as usize] >> 5 != 3_u8
            || ((68514004_i32 >> (env.current.as_bytes()[(env.cursor - 1) as usize] & 0x1f)) & 1)
                == 0
        {
            among_var = 3;
        } else {
            among_var = env.find_among_b(A_6, context);
        }
        match among_var {
            1 => {
                if !env.slice_from("e") {
                    return false;
                }
                return false;
            }
            2 => {
                let v_7 = env.limit - env.cursor;
                'lab5: {
                    if !env.in_grouping_b(G_AEO, 97, 111) {
                        break 'lab5;
                    }
                    if env.cursor > env.limit_backward {
                        break 'lab5;
                    }
                    return false;
                }
                env.cursor = env.limit - v_7;
            }
            3 => {
                if env.cursor != context.i_p1 {
                    return false;
                }
                let v_8 = env.limit - env.cursor;
                if !r_shortv(env, context) {
                    return false;
                }
                env.cursor = env.limit - v_8;
                if !env.slice_from("e") {
                    return false;
                }
                return false;
            }
            _ => (),
        }
        env.cursor = env.limit - v_6;
        env.ket = env.cursor;
        if env.cursor <= env.limit_backward {
            return false;
        }
        env.previous_char();
        env.bra = env.cursor;
        if !env.slice_del() {
            return false;
        }
        break 'lab0;
    }
    true
}

fn r_step_1c(env: &mut SnowballEnv, _context: &mut Context) -> bool {
    env.ket = env.cursor;
    'lab0: {
        let v_1 = env.limit - env.cursor;
        'lab1: {
            if !env.eq_s_b("y") {
                break 'lab1;
            }
            break 'lab0;
        }
        env.cursor = env.limit - v_1;
        if !env.eq_s_b("Y") {
            return false;
        }
        break 'lab0;
    }
    env.bra = env.cursor;
    if !env.out_grouping_b(G_V, 97, 121) {
        return false;
    }
    'lab2: {
        if env.cursor > env.limit_backward {
            break 'lab2;
        }
        return false;
    }
    if !env.slice_from("i") {
        return false;
    }
    true
}

fn r_step_2(env: &mut SnowballEnv, context: &mut Context) -> bool {
    env.ket = env.cursor;
    if env.cursor - 1 <= env.limit_backward
        || env.current.as_bytes()[(env.cursor - 1) as usize] >> 5 != 3_u8
        || ((1864192_i32 >> (env.current.as_bytes()[(env.cursor - 1) as usize] & 0x1f)) & 1) == 0
    {
        return false;
    }

    let among_var = env.find_among_b(A_7, context);
    if among_var == 0 {
        return false;
    }
    env.bra = env.cursor;
    if !r_r1(env, context) {
        return false;
    }
    match among_var {
        1 if !env.slice_from("tion") => {
            return false;
        }
        2 if !env.slice_from("ence") => {
            return false;
        }
        3 if !env.slice_from("ance") => {
            return false;
        }
        4 if !env.slice_from("able") => {
            return false;
        }
        5 if !env.slice_from("ent") => {
            return false;
        }
        6 if !env.slice_from("ize") => {
            return false;
        }
        7 if !env.slice_from("ate") => {
            return false;
        }
        8 if !env.slice_from("al") => {
            return false;
        }
        9 if !env.slice_from("ful") => {
            return false;
        }
        10 if !env.slice_from("ous") => {
            return false;
        }
        11 if !env.slice_from("ive") => {
            return false;
        }
        12 if !env.slice_from("ble") => {
            return false;
        }
        13 if !env.slice_from("og") => {
            return false;
        }
        14 => {
            if !env.eq_s_b("l") {
                return false;
            }
            if !env.slice_from("og") {
                return false;
            }
        }
        15 if !env.slice_from("less") => {
            return false;
        }
        16 => {
            if !env.in_grouping_b(G_VALID_LI, 99, 116) {
                return false;
            }
            if !env.slice_del() {
                return false;
            }
        }
        _ => (),
    }
    true
}

fn r_step_3(env: &mut SnowballEnv, context: &mut Context) -> bool {
    env.ket = env.cursor;
    if env.cursor - 2 <= env.limit_backward
        || env.current.as_bytes()[(env.cursor - 1) as usize] >> 5 != 3_u8
        || ((528928_i32 >> (env.current.as_bytes()[(env.cursor - 1) as usize] & 0x1f)) & 1) == 0
    {
        return false;
    }

    let among_var = env.find_among_b(A_8, context);
    if among_var == 0 {
        return false;
    }
    env.bra = env.cursor;
    if !r_r1(env, context) {
        return false;
    }
    match among_var {
        1 if !env.slice_from("tion") => {
            return false;
        }
        2 if !env.slice_from("ate") => {
            return false;
        }
        3 if !env.slice_from("al") => {
            return false;
        }
        4 if !env.slice_from("ic") => {
            return false;
        }
        5 if !env.slice_del() => {
            return false;
        }
        6 => {
            if !r_r2(env, context) {
                return false;
            }
            if !env.slice_del() {
                return false;
            }
        }
        _ => (),
    }
    true
}

fn r_step_4(env: &mut SnowballEnv, context: &mut Context) -> bool {
    env.ket = env.cursor;
    if env.cursor - 1 <= env.limit_backward
        || env.current.as_bytes()[(env.cursor - 1) as usize] >> 5 != 3_u8
        || ((1864232_i32 >> (env.current.as_bytes()[(env.cursor - 1) as usize] & 0x1f)) & 1) == 0
    {
        return false;
    }

    let among_var = env.find_among_b(A_9, context);
    if among_var == 0 {
        return false;
    }
    env.bra = env.cursor;
    if !r_r2(env, context) {
        return false;
    }
    match among_var {
        1 if !env.slice_del() => {
            return false;
        }
        2 => {
            'lab0: {
                let v_1 = env.limit - env.cursor;
                'lab1: {
                    if !env.eq_s_b("s") {
                        break 'lab1;
                    }
                    break 'lab0;
                }
                env.cursor = env.limit - v_1;
                if !env.eq_s_b("t") {
                    return false;
                }
                break 'lab0;
            }
            if !env.slice_del() {
                return false;
            }
        }
        _ => (),
    }
    true
}

fn r_step_5(env: &mut SnowballEnv, context: &mut Context) -> bool {
    env.ket = env.cursor;
    if env.cursor <= env.limit_backward
        || (env.current.as_bytes()[(env.cursor - 1) as usize] != 101_u8
            && env.current.as_bytes()[(env.cursor - 1) as usize] != 108_u8)
    {
        return false;
    }

    let among_var = env.find_among_b(A_10, context);
    if among_var == 0 {
        return false;
    }
    env.bra = env.cursor;
    match among_var {
        1 => {
            'lab0: {
                'lab1: {
                    if !r_r2(env, context) {
                        break 'lab1;
                    }
                    break 'lab0;
                }
                if !r_r1(env, context) {
                    return false;
                }
                let v_1 = env.limit - env.cursor;
                'lab2: {
                    if !r_shortv(env, context) {
                        break 'lab2;
                    }
                    return false;
                }
                env.cursor = env.limit - v_1;
                break 'lab0;
            }
            if !env.slice_del() {
                return false;
            }
        }
        2 => {
            if !r_r2(env, context) {
                return false;
            }
            if !env.eq_s_b("l") {
                return false;
            }
            if !env.slice_del() {
                return false;
            }
        }
        _ => (),
    }
    true
}

fn r_exception1(env: &mut SnowballEnv, context: &mut Context) -> bool {
    env.bra = env.cursor;
    if env.cursor + 2 >= env.limit
        || env.current.as_bytes()[(env.cursor + 2) as usize] >> 5 != 3_u8
        || ((42750482_i32 >> (env.current.as_bytes()[(env.cursor + 2) as usize] & 0x1f)) & 1) == 0
    {
        return false;
    }

    let among_var = env.find_among(A_11, context);
    if among_var == 0 {
        return false;
    }
    env.ket = env.cursor;
    if env.cursor < env.limit {
        return false;
    }
    match among_var {
        1 if !env.slice_from("sky") => {
            return false;
        }
        2 if !env.slice_from("idl") => {
            return false;
        }
        3 if !env.slice_from("gentl") => {
            return false;
        }
        4 if !env.slice_from("ugli") => {
            return false;
        }
        5 if !env.slice_from("earli") => {
            return false;
        }
        6 if !env.slice_from("onli") => {
            return false;
        }
        7 if !env.slice_from("singl") => {
            return false;
        }
        _ => (),
    }
    true
}

fn r_postlude(env: &mut SnowballEnv, context: &mut Context) -> bool {
    if !context.b_y_found {
        return false;
    }
    'replab0: loop {
        let v_1 = env.cursor;
        'lab1: {
            'golab2: loop {
                let v_2 = env.cursor;
                'lab3: {
                    env.bra = env.cursor;
                    if !env.eq_s("Y") {
                        break 'lab3;
                    }
                    env.ket = env.cursor;
                    env.cursor = v_2;
                    break 'golab2;
                }
                env.cursor = v_2;
                if env.cursor >= env.limit {
                    break 'lab1;
                }
                env.next_char();
            }
            if !env.slice_from("y") {
                return false;
            }
            continue 'replab0;
        }
        env.cursor = v_1;
        break 'replab0;
    }
    true
}

pub fn stem(env: &mut SnowballEnv) -> bool {
    let context = &mut Context {
        b_y_found: false,
        i_p2: 0,
        i_p1: 0,
    };
    'lab0: {
        let v_1 = env.cursor;
        'lab1: {
            if !r_exception1(env, context) {
                break 'lab1;
            }
            break 'lab0;
        }
        env.cursor = v_1;
        'lab2: {
            let v_2 = env.cursor;
            'lab3: {
                if !env.hop(3) {
                    break 'lab3;
                }
                break 'lab2;
            }
            env.cursor = v_2;
            break 'lab0;
        }
        env.cursor = v_1;
        r_prelude(env, context);
        r_mark_regions(env, context);
        env.limit_backward = env.cursor;
        env.cursor = env.limit;
        let v_3 = env.limit - env.cursor;
        r_step_1a(env, context);
        env.cursor = env.limit - v_3;
        let v_4 = env.limit - env.cursor;
        r_step_1b(env, context);
        env.cursor = env.limit - v_4;
        let v_5 = env.limit - env.cursor;
        r_step_1c(env, context);
        env.cursor = env.limit - v_5;
        let v_6 = env.limit - env.cursor;
        r_step_2(env, context);
        env.cursor = env.limit - v_6;
        let v_7 = env.limit - env.cursor;
        r_step_3(env, context);
        env.cursor = env.limit - v_7;
        let v_8 = env.limit - env.cursor;
        r_step_4(env, context);
        env.cursor = env.limit - v_8;
        let v_9 = env.limit - env.cursor;
        r_step_5(env, context);
        env.cursor = env.limit - v_9;
        env.cursor = env.limit_backward;
        let v_10 = env.cursor;
        r_postlude(env, context);
        env.cursor = v_10;
        break 'lab0;
    }
    true
}
