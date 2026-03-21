"""아카이브 검색 — 워크보드(현장관리) + A/S 과거 데이터 검색"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import text

from ..db import get_session
from ._helpers import _s


def register(mcp: FastMCP):

    @mcp.tool()
    def search_archive(
        query: str,
        board_type: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """과거 카카오워크 데이터 검색 (현장관리/A/S).
        워크보드 현장관리 게시글 + 댓글에서 키워드로 검색합니다.

        Args:
            query: 검색어 (현장명, 계약명, 모델명 등)
            board_type: 'site'=현장관리, 'as'=A/S, None=전체
            limit: 최대 결과 수
        """
        session = get_session()
        try:
            params = {'q': f'%{query}%', 'limit': limit}

            # 게시글 검색
            post_sql = """
                SELECT p.id, p.board_type, p.author, p.content_text,
                       p.children_count, p.created_at, p.updated_at,
                       p.contract_id,
                       c.contract_name, c.g2b_contract_no, c.payment_status
                FROM light_sync.archive_posts p
                LEFT JOIN light_sync.contracts c ON c.id = p.contract_id
                WHERE p.content_text ILIKE :q
            """
            if board_type:
                post_sql += " AND p.board_type = :bt"
                params['bt'] = board_type
            post_sql += " ORDER BY p.created_at DESC LIMIT :limit"

            posts = session.execute(text(post_sql), params).fetchall()

            # 댓글에서도 검색
            comment_sql = """
                SELECT c.post_id, c.author, c.content_text, c.created_at,
                       p.board_type, p.content_text as post_content
                FROM light_sync.archive_comments c
                JOIN light_sync.archive_posts p ON p.id = c.post_id
                WHERE c.content_text ILIKE :q
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
                    'created_at': _s(p.created_at),
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
                    'created_at': _s(c.created_at),
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
                'created_at': _s(post.created_at),
                'updated_at': _s(post.updated_at),
                'comments': [{
                    'author': _s(c.author),
                    'content': _s(c.content_text),
                    'created_at': _s(c.created_at),
                } for c in comments],
            }
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
