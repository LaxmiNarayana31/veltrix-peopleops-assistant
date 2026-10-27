"""Access service providing role-based security, document filtering, and authentication."""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select

from app.dto.chat_dto import RequestContext
from app.dto.document_dto import ManifestEntry
from app.exceptions.custom_exceptions import AppException, DatabaseException, UnauthorizedException
from app.models.employee_model import EmployeeModel
from app.utils.constants import UserRole
from config.app_config import MANIFEST_PATH
from config.database import get_db_session

logger = logging.getLogger(__name__)


class AccessService:
    """Handles role-based access control for employees, leave visibility, and documents."""

    _manifest_entries: Optional[Dict[str, ManifestEntry]] = None

    @classmethod
    def _get_manifest_dict(cls) -> Dict[str, ManifestEntry]:
        """Lazy load and return dictionary of manifest entries by doc_id."""
        if cls._manifest_entries is None:
            manifest_file = Path(MANIFEST_PATH)
            if manifest_file.exists():
                with open(manifest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cls._manifest_entries = {d["doc_id"]: ManifestEntry(**d) for d in data}
            else:
                cls._manifest_entries = {}
        return cls._manifest_entries

    @classmethod
    def get_manifest_entry(cls, doc_id: str) -> Optional[ManifestEntry]:
        """Retrieve manifest entry for a document ID."""
        return cls._get_manifest_dict().get(doc_id)

    @classmethod
    def eligible_doc_ids(cls, ctx: RequestContext, reference_date: date) -> Tuple[Set[str], Set[str]]:
        """Return tuple of (eligible_doc_ids, upcoming_doc_ids) based on Section 5 eligibility rules."""
        try:
            manifest_dict = cls._get_manifest_dict()
            eligible: Set[str] = set()
            upcoming: Set[str] = set()
            ref_iso = reference_date.isoformat()

            if ctx.role == UserRole.HR:
                allowed_levels = {"all", "managers", "hr"}
            elif ctx.role == UserRole.MANAGER:
                allowed_levels = {"all", "managers"}
            else:
                allowed_levels = {"all"}

            for doc_id, doc in manifest_dict.items():
                if doc.access_level not in allowed_levels:
                    continue

                regions = set(doc.regions)
                if ctx.region not in regions and "GLOBAL" not in regions:
                    continue

                if doc.effective_date <= ref_iso:
                    eligible.add(doc_id)
                else:
                    upcoming.add(doc_id)

            return eligible, upcoming
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed computing eligible documents for emp=%s", ctx.employee_id)
            return set(), set()

    @classmethod
    def get_employee(cls, employee_id: str) -> Optional[EmployeeModel]:
        """Fetch employee model from database by ID using SQLAlchemy ORM."""
        try:
            with get_db_session() as session:
                stmt = select(EmployeeModel).where(EmployeeModel.employee_id == employee_id)
                emp = session.scalar(stmt)
                if not emp:
                    return None
                session.expunge(emp)
                return emp
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to query employee %s", employee_id)
            raise DatabaseException("Error reading employee record") from exc

    @classmethod
    def authenticate_employee(cls, employee_id: Optional[str]) -> RequestContext:
        """Validate employee ID from request header and return RequestContext or raise 401."""
        try:
            if not employee_id:
                logger.warning("Authentication failed: missing X-Employee-Id header")
                raise UnauthorizedException("Missing X-Employee-Id header")

            employee = cls.get_employee(employee_id)
            if not employee:
                logger.warning("Authentication failed: employee %s not found in database", employee_id)
                raise UnauthorizedException("Unknown or invalid employee ID")

            role_val = UserRole(employee.role) if isinstance(employee.role, str) else employee.role
            return RequestContext(
                employee_id=employee.employee_id,
                role=role_val,
                region=employee.region,
                full_name=employee.full_name,
                email=employee.email,
            )
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Unexpected error during employee authentication")
            raise UnauthorizedException("Authentication failed") from exc

    @classmethod
    def can_view_employee(cls, ctx: RequestContext, target_employee_id: str) -> bool:
        """Check whether requester is permitted to view target employee's leave data."""
        try:
            if ctx.employee_id == target_employee_id:
                return True

            if ctx.role == UserRole.EMPLOYEE:
                return False

            if ctx.role == UserRole.HR:
                target = cls.get_employee(target_employee_id)
                return target is not None

            if ctx.role == UserRole.MANAGER:
                target = cls.get_employee(target_employee_id)
                if not target:
                    return False
                return target.manager_id == ctx.employee_id

            return False
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Error checking view permissions for emp=%s target=%s", ctx.employee_id, target_employee_id)
            return False

    @classmethod
    def get_direct_reports(cls, manager_id: str) -> List[EmployeeModel]:
        """Fetch all employees reporting directly to given manager ID using SQLAlchemy ORM."""
        try:
            with get_db_session() as session:
                stmt = (
                    select(EmployeeModel)
                    .where(EmployeeModel.manager_id == manager_id)
                    .order_by(EmployeeModel.employee_id)
                )
                reports = list(session.scalars(stmt).all())
                for r in reports:
                    session.expunge(r)
                return reports
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to query direct reports for manager %s", manager_id)
            raise DatabaseException("Error fetching direct reports") from exc

    @classmethod
    def find_employee_in_text(cls, text: str) -> Optional[EmployeeModel]:
        """Scan input text for any known employee full name or first name to support natural language queries."""
        try:
            if not text:
                return None
            text_lower = text.lower()
            with get_db_session() as session:
                all_emps = list(session.scalars(select(EmployeeModel)).all())
                # 1. Match full names first (highest confidence)
                for emp in all_emps:
                    if emp.full_name.lower() in text_lower:
                        session.expunge(emp)
                        return emp
                # 2. Match single distinctive first names (> 3 characters)
                words = re.findall(r"\b[A-Za-z]{4,}\b", text_lower)
                for w in words:
                    matches = [e for e in all_emps if e.full_name.lower().split()[0] == w]
                    if len(matches) == 1:
                        emp = matches[0]
                        session.expunge(emp)
                        return emp
                return None
        except Exception as exc:
            logger.exception("Error finding employee in text")
            return None


# Module-level singleton
_access_service: Optional[AccessService] = None


def get_access_service() -> AccessService:
    """Return singleton AccessService instance."""
    global _access_service
    if _access_service is None:
        _access_service = AccessService()
    return _access_service

# Aliases for helper usage
AccessHelper = AccessService
get_access_helper = get_access_service
