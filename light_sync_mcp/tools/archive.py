"""아카이브 검색 — 워크보드(현장관리) + A/S 과거 데이터 검색"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import text

from ..db import get_session
from ._helpers import _s, _sd


def register(mcp: FastMCP):

    @mcp.tool()
    def search_archive(
        query: str,
        board_type: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """워크보드/아카이브 검색 — 카카오워크 과거 현장관리·A/S 게시글과 댓글을 키워드로 검색합니다. '워크보드', '아카이브', '과거이력', 'A/S이력' 요청 시 이 도구를 사용하세요.

        Args:
            query: 검색어 (현장명, 계약명, 모델명 등)
            board_type: 'site'=현장관리, 'as'=A/S, None=전체
            limit: 최대 결과 수
        """
        session = get_session()
        try:
            # 검색어 분리 → AND/OR 조건 생성
            words = query.strip().split()
            params = {'limit': limit}
            idx = [0]  # mutable counter

            def _make_and(col, keyword_list):
                """키워드 리스트 → col ILIKE :q0 AND col ILIKE :q1 ..."""
                parts = []
                for kw in keyword_list:
                    key = f'q{idx[0]}'
                    idx[0] += 1
                    params[key] = f'%{kw}%'
                    parts.append(f"{col} ILIKE :{key}")
                return "(" + " AND ".join(parts) + ")"

            if len(words) >= 2:
                # 공백으로 분리된 경우: 각 단어 AND
                post_where = _make_and("p.content_text", words)
                comment_where = _make_and("c.content_text", words)
            else:
                q = query.strip()
                if len(q) > 2:
                    # 붙여쓰기: 원본 + 모든 2-way 분할(각 파트 2자 이상) → OR
                    groups_p = [_make_and("p.content_text", [q])]
                    groups_c = [_make_and("c.content_text", [q])]
                    for i in range(2, len(q) - 1):
                        groups_p.append(_make_and("p.content_text", [q[:i], q[i:]]))
                        groups_c.append(_make_and("c.content_text", [q[:i], q[i:]]))
                    post_where = " OR ".join(groups_p)
                    comment_where = " OR ".join(groups_c)
                else:
                    post_where = _make_and("p.content_text", [q])
                    comment_where = _make_and("c.content_text", [q])

            # 게시글 검색
            post_sql = f"""
                SELECT p.id, p.board_type, p.author, p.content_text,
                       p.children_count, p.created_at, p.updated_at,
                       p.contract_id,
                       c.contract_name, c.g2b_contract_no, c.payment_status
                FROM light_sync.archive_posts p
                LEFT JOIN light_sync.contracts c ON c.id = p.contract_id
                WHERE {post_where}
            """
            if board_type:
                post_sql += " AND p.board_type = :bt"
                params['bt'] = board_type
            post_sql += " ORDER BY p.created_at DESC LIMIT :limit"

            posts = session.execute(text(post_sql), params).fetchall()

            # 댓글에서도 검색
            comment_sql = f"""
                SELECT c.post_id, c.author, c.content_text, c.created_at,
                       p.board_type, p.content_text as post_content
                FROM light_sync.archive_comments c
                JOIN light_sync.archive_posts p ON p.id = c.post_id
                WHERE {comment_where}
            """
            if board_type:
                comment_sql += " AND p.board_type = :bt"
            comment_sql += " ORDER BY c.created_at DESC LIMIT :limit"

            comments = session.execute(text(comment_sql), params).fetchall()

            result = {
                'posts': [{
                    'id': p.id,
                    'board_type': '현장관리' if p.board_type == 'site' else 'A/S',
                    'author': _s(p.author),
                    'content': _s(p.content_text)[:500] if p.content_text else '',
                    'children_count': p.children_count,
                    'created_at': _sd(p.created_at),
                    'contract_id': p.contract_id,
                    'contract_name': _s(p.contract_name) if p.contract_id else None,
                    'g2b_no': _s(p.g2b_contract_no) if p.contract_id else None,
                    'payment_status': _s(p.payment_status) if p.contract_id else None,
                } for p in posts],
                'comments': [{
                    'post_id': c.post_id,
                    'board_type': '현장관리' if c.board_type == 'site' else 'A/S',
                    'author': _s(c.author),
                    'content': _s(c.content_text)[:300] if c.content_text else '',
                    'created_at': _sd(c.created_at),
                    'post_summary': _s(c.post_content)[:100] if c.post_content else '',
                } for c in comments],
            }
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()

    @mcp.tool()
    def get_archive_post_detail(
        post_id: int,
    ) -> str:
        """아카이브 게시글 상세 + 전체 댓글 조회.

        Args:
            post_id: 게시글 ID (search_archive 결과에서 확인)
        """
        session = get_session()
        try:
            post = session.execute(text(
                "SELECT * FROM light_sync.archive_posts WHERE id = :id"
            ), {'id': post_id}).first()
            if not post:
                return json.dumps({'error': '게시글을 찾을 수 없습니다'}, ensure_ascii=False)

            comments = session.execute(text(
                "SELECT * FROM light_sync.archive_comments WHERE post_id = :pid ORDER BY created_at"
            ), {'pid': post_id}).fetchall()

            result = {
                'id': post.id,
                'board_type': '현장관리' if post.board_type == 'site' else 'A/S',
                'author': _s(post.author),
                'content': _s(post.content_text),
                'created_at': _sd(post.created_at),
                'updated_at': _sd(post.updated_at),
                'comments': [{
                    'author': _s(c.author),
                    'content': _s(c.content_text),
                    'created_at': _sd(c.created_at),
                } for c in comments],
            }
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
